"""Pins the exact response shapes of every sharing endpoint.

The share/unshare/shared-users trio is implemented per entity; these snapshots
guarantee the factory refactor changes nothing observable.
"""

from database import db
from models import Clip, MediaType, TaskStatus


def _setup_two_users(client):
    """Register admin (first user) + second user. Return (admin_id, user2_id, client2)."""
    from fastapi.testclient import TestClient

    from main import app

    admin_resp = client.get('/auth/users')
    admin_id = next(u for u in admin_resp.json() if u['username'] == 'testadmin')['id']

    reg_resp = client.post('/auth/register', json={'username': 'user2', 'password': 'pass123'})
    user2_id = reg_resp.json()['id']
    client.post(f'/auth/users/{user2_id}/approve')

    client2 = TestClient(app)
    client2.post('/auth/login', json={'username': 'user2', 'password': 'pass123'})
    return admin_id, user2_id, client2


def _insert_clip(user_id: int) -> int:
    session = db.get_sync_session()
    try:
        clip = Clip(
            media_details_id=None,
            title='Snap Clip',
            start_time=0.0,
            end_time=5.0,
            duration=5.0,
            file_path=None,
            media_type=MediaType.AUDIO,
            status=TaskStatus.COMPLETE,
            user_id=user_id,
        )
        session.add(clip)
        session.commit()
        session.refresh(clip)
        return clip.id
    finally:
        session.close()


def _assert_trio(
    client, base: str, entity_id: int, id_key: str, user2_id: int, *, also_shared: tuple = ()
):
    """Assert the share/shared-users/unshare trio. `also_shared` = access rows seeded elsewhere."""
    share = client.post(f'{base}/{entity_id}/share', json={'user_id': user2_id})
    assert share.status_code == 201
    assert share.json() == {'status': 'shared', id_key: entity_id, 'user_id': user2_id}

    listed = client.get(f'{base}/{entity_id}/shared-users')
    assert listed.status_code == 200
    body = listed.json()
    assert set(body) == {id_key, 'shared_user_ids'}
    assert body[id_key] == entity_id
    assert sorted(body['shared_user_ids']) == sorted([*also_shared, user2_id])

    unshare = client.delete(f'{base}/{entity_id}/share/{user2_id}')
    assert unshare.status_code == 204

    again = client.delete(f'{base}/{entity_id}/share/{user2_id}')
    assert again.status_code == 404
    assert 'does not have shared access' in again.json()['detail']


def test_playlist_sharing_shapes(authenticated_client):
    _admin, user2_id, _c2 = _setup_two_users(authenticated_client)
    pl = authenticated_client.post('/playlists', json={'name': 'Snap'}).json()
    _assert_trio(authenticated_client, '/playlists', pl['id'], 'playlist_id', user2_id)


def test_subscription_sharing_shapes(authenticated_client):
    _admin, user2_id, _c2 = _setup_two_users(authenticated_client)
    _assert_trio(authenticated_client, '/subscriptions', 1, 'subscription_id', user2_id)


def test_clip_sharing_shapes(authenticated_client):
    admin_id, user2_id, _c2 = _setup_two_users(authenticated_client)
    clip_id = _insert_clip(admin_id)
    _assert_trio(authenticated_client, '/clips', clip_id, 'clip_id', user2_id)


def test_media_sharing_shapes(authenticated_client):
    admin_id, user2_id, _c2 = _setup_two_users(authenticated_client)
    # The owner holds a MediaAccess row of their own, so they list as a shared user too.
    _assert_trio(
        authenticated_client,
        '/media-details',
        1,
        'media_details_id',
        user2_id,
        also_shared=(admin_id,),
    )


def test_bulk_share_shapes(authenticated_client):
    _admin, user2_id, _c2 = _setup_two_users(authenticated_client)
    pl = authenticated_client.post('/playlists', json={'name': 'Bulk'}).json()

    resp = authenticated_client.post(
        '/playlists/share/bulk',
        json={'entity_ids': [pl['id'], 999999], 'user_ids': [user2_id]},
    )
    assert resp.status_code == 201
    assert resp.json() == {
        'shared_count': 1,
        'errors': [{'playlist_id': 999999, 'error': 'not found or not owner'}],
    }

    resp = authenticated_client.post(
        '/subscriptions/share/bulk', json={'entity_ids': [1], 'user_ids': [user2_id]}
    )
    assert resp.status_code == 201
    assert resp.json() == {'shared_count': 1, 'errors': []}

    resp = authenticated_client.post(
        '/media-details/share/bulk', json={'entity_ids': [2], 'user_ids': [user2_id]}
    )
    assert resp.status_code == 201
    assert resp.json() == {'shared_count': 1, 'errors': []}
