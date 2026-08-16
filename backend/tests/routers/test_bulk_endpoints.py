"""End-to-end tests for the server-side bulk endpoints that replaced the
former client-side per-item request fan-outs (add-to-playlist, delete, tag,
clip delete, share). These validate routing (incl. /bulk vs /{id} ordering),
request/response shapes, and that the server returns accurate counts.
"""

from sqlmodel import select

from database import db
from models import Clip, MediaAccess, MediaDetails, MediaType, TaskStatus


def _get_admin_id(client) -> int:
    users = client.get('/auth/users').json()
    return next(u for u in users if u['username'] == 'testadmin')['id']


def _insert_clip(user_id: int, title: str, media_details_id: int = 1) -> int:
    session = db.get_sync_session()
    try:
        clip = Clip(
            media_details_id=media_details_id,
            title=title,
            start_time=0.0,
            end_time=5.0,
            media_type=MediaType.AUDIO,
            file_path='/tmp/nonexistent-clip.m4a',
            user_id=user_id,
        )
        session.add(clip)
        session.commit()
        session.refresh(clip)
        return clip.id
    finally:
        session.close()


async def test_playlist_bulk_add_endpoint(authenticated_client):
    pl = authenticated_client.post('/playlists', json={'name': 'P'})
    assert pl.status_code == 201, pl.text
    pid = pl.json()['id']

    resp = authenticated_client.post(
        f'/playlists/{pid}/media/bulk', json={'media_details_ids': [1, 2]}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body['added'] == 2
    assert body['already_present'] == 0

    media = authenticated_client.get(f'/playlists/{pid}/media').json()
    assert media['count_records'] == 2

    # Second identical call is idempotent and honestly reported.
    resp2 = authenticated_client.post(
        f'/playlists/{pid}/media/bulk', json={'media_details_ids': [1, 2]}
    )
    assert resp2.json()['added'] == 0
    assert resp2.json()['already_present'] == 2


async def test_media_bulk_delete_endpoint(authenticated_client):
    resp = authenticated_client.request(
        'DELETE',
        '/media-details/bulk-delete',
        json={'media_details_ids': [1], 'keep_transcripts': True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()['deleted'] == 1

    session = db.get_sync_session()
    try:
        media = session.execute(select(MediaDetails).where(MediaDetails.id == 1)).scalar_one()
    finally:
        session.close()
    assert media.status == TaskStatus.DELETED


async def test_media_bulk_tags_endpoint(authenticated_client):
    resp = authenticated_client.put(
        '/media-details/bulk-tags',
        json={'media_details_ids': [1, 2], 'tag_names': ['alpha', 'beta']},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['tagged_count'] == 2
    assert body['associations_added'] == 4  # 2 media x 2 tags

    detail = authenticated_client.get('/media-details/1').json()
    tag_names = {t['name'] for t in detail['tags']}
    assert {'alpha', 'beta'} <= tag_names

    # Re-applying the same tags adds no new associations.
    resp2 = authenticated_client.put(
        '/media-details/bulk-tags',
        json={'media_details_ids': [1, 2], 'tag_names': ['alpha', 'beta']},
    )
    assert resp2.json()['associations_added'] == 0


async def test_clip_bulk_delete_endpoint(authenticated_client):
    admin_id = _get_admin_id(authenticated_client)
    c1 = _insert_clip(admin_id, 'clip1')
    c2 = _insert_clip(admin_id, 'clip2')

    resp = authenticated_client.request('DELETE', '/clips/bulk', json={'clip_ids': [c1, c2]})
    assert resp.status_code == 200, resp.text
    assert resp.json()['deleted_count'] == 2

    session = db.get_sync_session()
    try:
        remaining = session.execute(select(Clip).where(Clip.id.in_([c1, c2]))).scalars().all()
    finally:
        session.close()
    assert remaining == []


async def test_media_bulk_share_endpoint(authenticated_client):
    reg = authenticated_client.post(
        '/auth/register', json={'username': 'user2', 'password': 'pass12345'}
    )
    assert reg.status_code == 201, reg.text
    user2_id = reg.json()['id']

    resp = authenticated_client.post(
        '/media-details/share/bulk',
        json={'entity_ids': [1, 2], 'user_ids': [user2_id]},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()['shared_count'] == 2  # 2 media x 1 user

    session = db.get_sync_session()
    try:
        access = (
            session.execute(select(MediaAccess).where(MediaAccess.user_id == user2_id))
            .scalars()
            .all()
        )
    finally:
        session.close()
    assert {1, 2} <= {a.media_details_id for a in access}
