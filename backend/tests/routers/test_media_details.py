import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from sqlmodel import select

from database import db
from models import (
    MediaAccess,
    MediaDetails,
    PlaybackState,
    SourceType,
    TaskRecord,
    TaskStatus,
    TaskType,
)


def _setup_two_users(client):
    """Register admin (first user) + second user. Return (admin_id, user2_id, client2)."""
    from fastapi.testclient import TestClient

    from main import app

    admin_resp = client.get('/auth/users')
    admin_user = next(u for u in admin_resp.json() if u['username'] == 'testadmin')
    admin_id = admin_user['id']

    reg_resp = client.post('/auth/register', json={'username': 'user2', 'password': 'pass123'})
    user2_id = reg_resp.json()['id']
    client.post(f'/auth/users/{user2_id}/approve')

    client2 = TestClient(app)
    client2.post('/auth/login', json={'username': 'user2', 'password': 'pass123'})

    return admin_id, user2_id, client2


def _setup_three_users(client):
    """Register admin + user2 + user3. Return (admin_id, user2_id, client2, user3_id, client3)."""
    from fastapi.testclient import TestClient

    from main import app

    admin_id, user2_id, client2 = _setup_two_users(client)

    reg_resp = client.post('/auth/register', json={'username': 'user3', 'password': 'pass123'})
    user3_id = reg_resp.json()['id']
    client.post(f'/auth/users/{user3_id}/approve')

    client3 = TestClient(app)
    client3.post('/auth/login', json={'username': 'user3', 'password': 'pass123'})

    return admin_id, user2_id, client2, user3_id, client3


def _count_media_access(user_id, media_id, source_type=None, source_id=None):
    """Count MediaAccess rows matching the given criteria."""
    session = db.get_sync_session()
    try:
        conditions = [
            MediaAccess.user_id == user_id,
            MediaAccess.media_details_id == media_id,
        ]
        if source_type is not None:
            conditions.append(MediaAccess.source_type == source_type)
        if source_id is not None:
            conditions.append(MediaAccess.source_id == source_id)

        stmt = select(MediaAccess).where(*conditions)
        result = session.execute(stmt)
        return len(result.scalars().all())
    finally:
        session.close()


def _get_media_owner_id(media_id):
    """Get the owner_id of a MediaDetails record directly from DB."""
    session = db.get_sync_session()
    try:
        stmt = select(MediaDetails).where(MediaDetails.id == media_id)
        result = session.execute(stmt)
        md = result.scalar_one_or_none()
        return md.owner_id if md else None
    finally:
        session.close()


def _get_media_status(media_id):
    """Get the status of a MediaDetails record directly from DB."""
    session = db.get_sync_session()
    try:
        stmt = select(MediaDetails).where(MediaDetails.id == media_id)
        result = session.execute(stmt)
        md = result.scalar_one_or_none()
        return md.status.value if md else None
    finally:
        session.close()


def test_get_one_media_detail(authenticated_client):
    response = authenticated_client.get('/media-details/1')
    assert response.status_code == 200
    data = response.json()
    assert data['id'] == 1
    assert data['url'] == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


def test_get_one_media_detail_not_exist(authenticated_client):
    response = authenticated_client.get('/media-details/999')
    assert response.status_code == 404


def test_get_all_media_details(authenticated_client):
    # admin_view=true because test user is admin and has no media_access rows
    response = authenticated_client.get('/media-details?page=1&page_size=25&admin_view=true')
    assert response.status_code == 200
    data = response.json()
    assert 'records' in data
    assert 'count_records' in data
    assert data['count_records'] >= 2
    assert len(data['records']) >= 2

    response = authenticated_client.get('/media-details?page=1&page_size=1&admin_view=true')
    assert response.status_code == 200
    assert len(response.json()['records']) == 1
    md_1 = response.json()['records'][0]

    response = authenticated_client.get('/media-details?page=2&page_size=1&admin_view=true')
    assert response.status_code == 200
    assert len(response.json()['records']) == 1
    md_2 = response.json()['records'][0]

    assert md_1['id'] != md_2['id']


def test_soft_delete_removes_media_from_playlists(authenticated_client):
    """Soft-deleting media via the API removes it from all playlists."""
    # Create a playlist
    create_resp = authenticated_client.post('/playlists', json={'name': 'Delete Test Playlist'})
    assert create_resp.status_code == 201
    playlist_id = create_resp.json()['id']

    # Add media 1 and 2 to the playlist
    add_resp_1 = authenticated_client.post(
        f'/playlists/{playlist_id}/media',
        json={'media_details_id': 1, 'position': 1},
    )
    assert add_resp_1.status_code == 201

    add_resp_2 = authenticated_client.post(
        f'/playlists/{playlist_id}/media',
        json={'media_details_id': 2, 'position': 2},
    )
    assert add_resp_2.status_code == 201

    # Verify both are present
    media_resp = authenticated_client.get(f'/playlists/{playlist_id}/media')
    assert media_resp.status_code == 200
    assert media_resp.json()['count_records'] == 2

    # Soft-delete media 1
    delete_resp = authenticated_client.delete('/media-details/1')
    assert delete_resp.status_code == 204

    # Playlist should now only contain media 2, at position 1
    media_resp = authenticated_client.get(f'/playlists/{playlist_id}/media')
    assert media_resp.status_code == 200
    data = media_resp.json()
    assert data['count_records'] == 1
    assert data['records'][0]['media_details_id'] == 2
    assert data['records'][0]['position'] == 1


def test_unauthenticated_rejected(test_database):
    """Unauthenticated requests to media-details endpoints return 401."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    response = client.get('/media-details')
    assert response.status_code == 401


# --- Sharing tests ---


def test_share_media_happy_path(authenticated_client):
    """Owner can share a media item with another user."""
    # Register a second user
    authenticated_client.post(
        '/auth/register', json={'username': 'shareuser', 'password': 'pass123'}
    )
    # Approve the second user (authenticated_client is admin)
    users_resp = authenticated_client.get('/auth/users')
    second_user = next(u for u in users_resp.json() if u['username'] == 'shareuser')
    authenticated_client.post(f'/auth/users/{second_user["id"]}/approve')

    # Share media 1 with the second user
    resp = authenticated_client.post('/media-details/1/share', json={'user_id': second_user['id']})
    assert resp.status_code == 201
    assert resp.json()['status'] == 'shared'

    # Verify shared users list includes the second user
    shared_resp = authenticated_client.get('/media-details/1/shared-users')
    assert shared_resp.status_code == 200
    assert second_user['id'] in shared_resp.json()['shared_user_ids']


def test_unshare_media(authenticated_client):
    """Owner can revoke sharing access."""
    # Register + approve a second user
    authenticated_client.post(
        '/auth/register', json={'username': 'unshareuser', 'password': 'pass123'}
    )
    users_resp = authenticated_client.get('/auth/users')
    second_user = next(u for u in users_resp.json() if u['username'] == 'unshareuser')
    authenticated_client.post(f'/auth/users/{second_user["id"]}/approve')

    # Share, then unshare
    authenticated_client.post('/media-details/1/share', json={'user_id': second_user['id']})
    resp = authenticated_client.delete(f'/media-details/1/share/{second_user["id"]}')
    assert resp.status_code == 204

    # Verify user is no longer in shared list
    shared_resp = authenticated_client.get('/media-details/1/shared-users')
    assert second_user['id'] not in shared_resp.json()['shared_user_ids']


def test_unshare_nonexistent_access(authenticated_client):
    """Unsharing a user who doesn't have access returns 404."""
    resp = authenticated_client.delete('/media-details/1/share/99999')
    assert resp.status_code == 404


def test_share_media_not_found(authenticated_client):
    """Sharing a non-existent media item returns 404."""
    resp = authenticated_client.post('/media-details/99999/share', json={'user_id': 1})
    assert resp.status_code == 404


def test_get_shared_users_not_found(authenticated_client):
    """Getting shared users for a non-existent media returns 404."""
    resp = authenticated_client.get('/media-details/99999/shared-users')
    assert resp.status_code == 404


def test_share_media_non_owner_rejected(test_database):
    """A non-owner cannot share a media item."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)

    # Register first user (admin, owner of test data)
    client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})

    # Register + approve second user
    resp = client.post('/auth/register', json={'username': 'noowner', 'password': 'pass123'})
    second_user_id = resp.json()['id']
    client.post(f'/auth/users/{second_user_id}/approve')

    # Log in as second user
    client2 = TestClient(app)
    client2.post('/auth/login', json={'username': 'noowner', 'password': 'pass123'})

    # Try to share media 1 (owned by admin) — should get 404
    share_resp = client2.post('/media-details/1/share', json={'user_id': second_user_id})
    assert share_resp.status_code == 404


# --- Ownership transfer on delete tests ---


def test_owner_delete_with_direct_user_transfers_ownership(authenticated_client):
    """When owner deletes media that has another user with direct access, ownership transfers."""
    admin_id, user2_id, _client2 = _setup_two_users(authenticated_client)

    # Share media 1 directly with user2 (gives user2 source_type=SourceType.DIRECT access)
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})
    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 1

    # Owner deletes media 1
    resp = authenticated_client.delete('/media-details/1')
    assert resp.status_code == 204

    # Media should still be COMPLETE (not DELETED)
    assert _get_media_status(1) == 'COMPLETE'

    # owner_id should now be user2
    assert _get_media_owner_id(1) == user2_id

    # Owner (admin) should have lost all access rows for this media
    assert _count_media_access(admin_id, 1) == 0

    # user2 should still have their direct access
    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 1


def test_owner_delete_without_direct_users_soft_deletes(authenticated_client):
    """When owner deletes media with no other direct users, normal soft delete occurs."""
    admin_id, _user2_id, _client2 = _setup_two_users(authenticated_client)

    # Don't share media 2 with anyone — owner is the only direct user

    # Owner deletes media 2
    resp = authenticated_client.delete('/media-details/2')
    assert resp.status_code == 204

    # Media should be DELETED
    assert _get_media_status(2) == 'DELETED'

    # All access rows should be cleaned up
    assert _count_media_access(admin_id, 2) == 0


def test_transferred_media_accessible_to_new_owner(authenticated_client):
    """After transfer, the new owner can GET the media and sees correct owner_id."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Share media 1 directly with user2
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})

    # Owner deletes → triggers transfer
    authenticated_client.delete('/media-details/1')

    # user2 can access the media
    resp = client2.get('/media-details/1')
    assert resp.status_code == 200
    assert resp.json()['owner_id'] == user2_id


def test_multiple_direct_users_earliest_gets_ownership(authenticated_client):
    """With multiple direct users, the earliest (by created_at) gets ownership."""
    admin_id, user2_id, _client2, user3_id, _client3 = _setup_three_users(authenticated_client)

    # Share media 1 with user2 first, then user3
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})
    # Small sleep to ensure created_at ordering is deterministic
    time.sleep(0.05)
    authenticated_client.post('/media-details/1/share', json={'user_id': user3_id})

    # Owner deletes → should transfer to user2 (earliest direct access)
    resp = authenticated_client.delete('/media-details/1')
    assert resp.status_code == 204

    # owner_id should be user2 (earliest)
    assert _get_media_owner_id(1) == user2_id
    assert _get_media_status(1) == 'COMPLETE'

    # user3 should still have their direct access
    assert _count_media_access(user3_id, 1, SourceType.DIRECT, 0) == 1

    # Admin should have lost all access
    assert _count_media_access(admin_id, 1) == 0


def _grant_subscription_access_row(user_id, media_id, subscription_id=1):
    """Insert a SUBSCRIPTION-sourced MediaAccess row (mimics subscription dedup grant)."""
    session = db.get_sync_session()
    try:
        session.add(
            MediaAccess(
                user_id=user_id,
                media_details_id=media_id,
                source_type=SourceType.SUBSCRIPTION,
                source_id=subscription_id,
            )
        )
        session.commit()
    finally:
        session.close()


def test_owner_delete_with_subscription_user_transfers_ownership(authenticated_client):
    """A subscription-dedup access holder is a transfer candidate: the file is preserved
    and ownership moves instead of soft-deleting."""
    admin_id, user2_id, _client2 = _setup_two_users(authenticated_client)

    # user2 got access via subscription dedup (not an explicit share)
    _grant_subscription_access_row(user2_id, 1)

    resp = authenticated_client.delete('/media-details/1')
    assert resp.status_code == 204

    # File preserved: record stays COMPLETE and ownership moved to user2
    assert _get_media_status(1) == 'COMPLETE'
    assert _get_media_owner_id(1) == user2_id

    # Old owner lost all access; new owner got an owner-style DIRECT row so later
    # unshare/unsubscribe cascades can't strip visibility of media they now own
    assert _count_media_access(admin_id, 1) == 0
    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 1


def test_transfer_prefers_direct_over_earlier_subscription_access(authenticated_client):
    """DIRECT access holders outrank SUBSCRIPTION holders even with a later created_at."""
    _admin_id, user2_id, _client2, user3_id, _client3 = _setup_three_users(authenticated_client)

    # user2 gets subscription-sourced access first...
    _grant_subscription_access_row(user2_id, 1)
    time.sleep(0.05)
    # ...user3 gets an explicit direct share afterwards
    authenticated_client.post('/media-details/1/share', json={'user_id': user3_id})

    resp = authenticated_client.delete('/media-details/1')
    assert resp.status_code == 204

    # DIRECT holder wins despite the later grant
    assert _get_media_owner_id(1) == user3_id
    assert _get_media_status(1) == 'COMPLETE'

    # user2 keeps their subscription-sourced access to the transferred media
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION) == 1


def test_admin_deleting_others_media_force_deletes(authenticated_client):
    """Admin deleting another user's media always force-deletes (bypasses transfer)."""
    admin_id, user2_id, _client2, user3_id, _client3 = _setup_three_users(authenticated_client)

    # Transfer ownership of media 2 to user2
    session = db.get_sync_session()
    try:
        stmt = select(MediaDetails).where(MediaDetails.id == 2)
        md = session.execute(stmt).scalar_one()
        md.owner_id = user2_id
        session.commit()
    finally:
        session.close()

    # Give user3 direct access to media 2 (admin_view needed since admin no longer owns it)
    authenticated_client.post('/media-details/2/share?admin_view=true', json={'user_id': user3_id})

    # Admin deletes media 2 (admin is NOT the owner — user2 is)
    resp = authenticated_client.delete('/media-details/2')
    assert resp.status_code == 204

    # Should be a force soft delete, NOT a transfer — even though user3 has direct access
    assert _get_media_status(2) == 'DELETED'

    # All access rows should be cleaned up
    assert _count_media_access(user2_id, 2) == 0
    assert _count_media_access(user3_id, 2) == 0
    assert _count_media_access(admin_id, 2) == 0


# --- Admin Mode sharing tests ---


def test_share_media_admin_without_admin_view_rejected(authenticated_client):
    """Admin who doesn't own media gets 404 when sharing without admin_view=true."""
    _admin_id, user2_id, _client2 = _setup_two_users(authenticated_client)

    # Transfer ownership of media 2 to user2
    session = db.get_sync_session()
    try:
        stmt = select(MediaDetails).where(MediaDetails.id == 2)
        md = session.execute(stmt).scalar_one()
        md.owner_id = user2_id
        session.commit()
    finally:
        session.close()

    # Admin tries to share media 2 without admin_view — should be rejected
    resp = authenticated_client.post('/media-details/2/share', json={'user_id': user2_id})
    assert resp.status_code == 404

    # Also verify shared-users and unshare are blocked
    resp = authenticated_client.get('/media-details/2/shared-users')
    assert resp.status_code == 404


def test_share_media_admin_with_admin_view_allowed(authenticated_client):
    """Admin who doesn't own media can share when admin_view=true is passed."""
    _admin_id, user2_id, _client2, user3_id, _client3 = _setup_three_users(authenticated_client)

    # Transfer ownership of media 2 to user2
    session = db.get_sync_session()
    try:
        stmt = select(MediaDetails).where(MediaDetails.id == 2)
        md = session.execute(stmt).scalar_one()
        md.owner_id = user2_id
        session.commit()
    finally:
        session.close()

    # Admin shares media 2 with user3 using admin_view=true — should succeed
    resp = authenticated_client.post(
        '/media-details/2/share?admin_view=true', json={'user_id': user3_id}
    )
    assert resp.status_code == 201
    assert resp.json()['status'] == 'shared'

    # Verify shared users list works with admin_view
    shared_resp = authenticated_client.get('/media-details/2/shared-users?admin_view=true')
    assert shared_resp.status_code == 200
    assert user3_id in shared_resp.json()['shared_user_ids']

    # Unshare with admin_view=true — should also work
    unshare_resp = authenticated_client.delete(f'/media-details/2/share/{user3_id}?admin_view=true')
    assert unshare_resp.status_code == 204


# --- Playback state tests ---


def _get_playback_state(user_id, media_id):
    """Get PlaybackState directly from DB."""
    session = db.get_sync_session()
    try:
        stmt = select(PlaybackState).where(
            PlaybackState.user_id == user_id,
            PlaybackState.media_details_id == media_id,
        )
        result = session.execute(stmt)
        return result.scalar_one_or_none()
    finally:
        session.close()


def test_patch_playback_creates_state(authenticated_client):
    """First PATCH to playback creates a new PlaybackState record."""
    resp = authenticated_client.patch(
        '/media-details/1/playback',
        json={
            'playback_position': 42.5,
            'last_accessed': datetime.now(UTC).isoformat(),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['playback_position'] == 42.5
    assert data['access_count'] == 1


def test_patch_playback_updates_existing(authenticated_client):
    """Subsequent PATCHes update the existing PlaybackState."""
    # First PATCH
    authenticated_client.patch(
        '/media-details/1/playback',
        json={
            'playback_position': 10.0,
            'last_accessed': '2020-01-01T00:00:00Z',
        },
    )

    # Second PATCH (> 60s later in last_accessed — triggers access_count increment)
    resp = authenticated_client.patch(
        '/media-details/1/playback',
        json={
            'playback_position': 20.0,
            'last_accessed': '2020-01-01T00:02:00Z',
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['playback_position'] == 20.0
    assert data['access_count'] == 2


def test_patch_playback_debounce(authenticated_client):
    """Access count does not increment for PATCHes within 60 seconds."""
    # First PATCH
    authenticated_client.patch(
        '/media-details/2/playback',
        json={
            'playback_position': 5.0,
            'last_accessed': '2020-06-01T12:00:00Z',
        },
    )

    # Second PATCH only 10s later — should NOT increment
    resp = authenticated_client.patch(
        '/media-details/2/playback',
        json={
            'playback_position': 10.0,
            'last_accessed': '2020-06-01T12:00:10Z',
        },
    )
    assert resp.status_code == 200
    assert resp.json()['access_count'] == 1  # Still 1, not 2


def test_two_users_independent_playback(authenticated_client):
    """Two users have independent playback state for the same media."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Share media 1 with user2
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})

    # Admin sets position to 100
    authenticated_client.patch(
        '/media-details/1/playback',
        json={
            'playback_position': 100.0,
            'last_accessed': datetime.now(UTC).isoformat(),
        },
    )

    # User2 sets position to 200
    client2.patch(
        '/media-details/1/playback',
        json={
            'playback_position': 200.0,
            'last_accessed': datetime.now(UTC).isoformat(),
        },
    )

    # Admin GETs media — should see their own position (100)
    admin_resp = authenticated_client.get('/media-details/1')
    assert admin_resp.status_code == 200
    assert admin_resp.json()['playback_position'] == 100.0

    # User2 GETs media — should see their own position (200)
    user2_resp = client2.get('/media-details/1')
    assert user2_resp.status_code == 200
    assert user2_resp.json()['playback_position'] == 200.0


def test_patch_playback_not_found(authenticated_client):
    """PATCH to non-existent media returns 404."""
    resp = authenticated_client.patch(
        '/media-details/99999/playback',
        json={'playback_position': 5.0},
    )
    assert resp.status_code == 404


def test_patch_playback_access_control(authenticated_client):
    """Non-owner without access cannot PATCH playback."""
    _admin_id, _user2_id, client2 = _setup_two_users(authenticated_client)

    # user2 tries to PATCH media 1 without access
    resp = client2.patch(
        '/media-details/1/playback',
        json={'playback_position': 5.0},
    )
    # Should be 404 (check_access_or_raise raises 404 for unauthorized)
    assert resp.status_code == 404


def test_get_media_details_includes_playback(authenticated_client):
    """GET /media-details/{id} includes playback fields from PlaybackState."""
    # Set some playback state first
    authenticated_client.patch(
        '/media-details/1/playback',
        json={
            'playback_position': 55.5,
            'last_accessed': datetime.now(UTC).isoformat(),
        },
    )

    resp = authenticated_client.get('/media-details/1')
    assert resp.status_code == 200
    data = resp.json()
    assert data['playback_position'] == 55.5
    assert data['last_accessed'] is not None
    assert data['access_count'] >= 1


def test_get_media_details_no_playback_state(authenticated_client):
    """GET returns defaults when no PlaybackState exists for the user."""
    resp = authenticated_client.get('/media-details/2')
    assert resp.status_code == 200
    data = resp.json()
    assert data['playback_position'] is None
    assert data['last_accessed'] is None
    assert data['access_count'] == 0


def test_list_media_details_includes_playback(authenticated_client):
    """GET /media-details list endpoint includes playback fields."""
    # Set playback state for media 1
    authenticated_client.patch(
        '/media-details/1/playback',
        json={
            'playback_position': 30.0,
            'last_accessed': datetime.now(UTC).isoformat(),
        },
    )

    resp = authenticated_client.get('/media-details?page=1&page_size=25')
    assert resp.status_code == 200
    records = resp.json()['records']
    # Find media 1 in the results
    media_1 = next(r for r in records if r['id'] == 1)
    assert media_1['playback_position'] == 30.0
    assert media_1['access_count'] >= 1


# --- Thumbnail path tests ---


def test_thumbnail_path_stored_and_returned(authenticated_client):
    """Creating media with thumbnail_path stores it and returns it via GET."""
    from models import MediaType, TaskStatus

    session = db.get_sync_session()
    try:
        md = MediaDetails(
            url='https://www.youtube.com/watch?v=thumbnail_test',
            media_type=MediaType.AUDIO,
            channel='Thumb Channel',
            title='Thumbnail Test Video',
            status=TaskStatus.COMPLETE,
            thumbnail_path='/mnt/audio/thumb_test.thumb.jpg',
        )
        session.add(md)
        session.commit()
        session.refresh(md)
        media_id = md.id

        # Grant access to the test user
        users_resp = authenticated_client.get('/auth/users')
        user_id = next(u for u in users_resp.json() if u['username'] == 'testadmin')['id']
        session.add(MediaAccess(user_id=user_id, media_details_id=media_id))
        session.commit()
    finally:
        session.close()

    # GET single media — should include thumbnail_path
    resp = authenticated_client.get(f'/media-details/{media_id}')
    assert resp.status_code == 200
    assert resp.json()['thumbnail_path'] == '/mnt/audio/thumb_test.thumb.jpg'


def test_thumbnail_path_null_by_default(authenticated_client):
    """Existing media without thumbnail_path returns null."""
    resp = authenticated_client.get('/media-details/1')
    assert resp.status_code == 200
    assert resp.json()['thumbnail_path'] is None


def test_get_thumbnail_endpoint(authenticated_client, tmp_path):
    """GET /media/{id}/thumbnail returns the thumbnail image when it exists."""
    from models import MediaType, TaskStatus

    # Create a temporary thumbnail file
    thumb_file = tmp_path / 'test_video.thumb.jpg'
    thumb_file.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100)  # Minimal JPEG-like data

    session = db.get_sync_session()
    try:
        md = MediaDetails(
            url='https://www.youtube.com/watch?v=thumb_endpoint_test',
            media_type=MediaType.VIDEO,
            channel='Thumb Channel',
            title='Thumbnail Endpoint Test',
            status=TaskStatus.COMPLETE,
            file_path=str(tmp_path / 'test_video.mp4'),
            thumbnail_path=str(thumb_file),
        )
        session.add(md)
        session.commit()
        session.refresh(md)
        media_id = md.id

        users_resp = authenticated_client.get('/auth/users')
        user_id = next(u for u in users_resp.json() if u['username'] == 'testadmin')['id']
        session.add(MediaAccess(user_id=user_id, media_details_id=media_id))
        session.commit()
    finally:
        session.close()

    resp = authenticated_client.get(f'/media/{media_id}/thumbnail')
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'image/jpeg'
    assert 'max-age=86400' in resp.headers.get('cache-control', '')


def test_get_thumbnail_not_found(authenticated_client):
    """GET /media/{id}/thumbnail returns 404 when no thumbnail exists."""
    resp = authenticated_client.get('/media/1/thumbnail')
    assert resp.status_code == 404


# --- TaskRecord user_id regression tests ---


def _get_admin_id(client) -> int:
    users = client.get('/auth/users').json()
    return next(u for u in users if u['username'] == 'testadmin')['id']


def _mock_orch_submit(monkeypatch) -> AsyncMock:
    """Mock the orchestrator submit so no real job is enqueued.

    The endpoint returns its own pre-assigned transcript task_id, so the mock
    just needs to swallow the JobSpec.
    """
    mock = AsyncMock(side_effect=lambda spec: spec.task_id)
    monkeypatch.setattr('routers.media_details.orch.submit', mock)
    return mock


def test_create_transcript_sets_task_record_user_id(monkeypatch, authenticated_client):
    """Manual transcript creation must persist the authenticated user as task owner."""
    _mock_orch_submit(monkeypatch)
    monkeypatch.setattr('routers.media_details.publish_status_change', MagicMock())

    admin_id = _get_admin_id(authenticated_client)

    # Media id=2 has no existing transcript_task_record_id (per conftest fixture),
    # so this exercises the "create new TaskRecord" branch.
    response = authenticated_client.post('/media-details/transcripts/2/create')
    assert response.status_code == 200, response.text
    task_id = response.json()['task']

    session = db.get_sync_session()
    try:
        task_record = session.execute(
            select(TaskRecord).where(TaskRecord.task_id == task_id)
        ).scalar_one()
    finally:
        session.close()

    assert task_record.user_id == admin_id, (
        f'Expected TaskRecord.user_id={admin_id}, got {task_record.user_id}'
    )


def test_retry_transcript_backfills_null_user_id(monkeypatch, authenticated_client):
    """Retrying a transcript must backfill user_id on the reused TaskRecord."""
    _mock_orch_submit(monkeypatch)
    monkeypatch.setattr('routers.media_details.publish_status_change', MagicMock())

    admin_id = _get_admin_id(authenticated_client)

    # Pre-insert a NULL-owner CANCELLED TaskRecord and link it to media 2.
    # TaskRecord.user_id is ondelete='SET NULL', so deleting an owner leaves rows here.
    session = db.get_sync_session()
    try:
        unowned = TaskRecord(
            task_id='unowned-transcript',
            task_type=TaskType.TRANSCRIPT_GENERATION,
            status=TaskStatus.CANCELLED,
            user_id=None,
            title='Unowned Title',
            channel='Unowned Channel',
        )
        session.add(unowned)
        session.commit()
        session.refresh(unowned)
        unowned_id = unowned.id

        md = session.execute(select(MediaDetails).where(MediaDetails.id == 2)).scalar_one()
        md.transcript_task_record_id = unowned_id
        session.add(md)
        session.commit()
    finally:
        session.close()

    response = authenticated_client.post('/media-details/transcripts/2/create')
    assert response.status_code == 200, response.text
    new_task_id = response.json()['task']

    session = db.get_sync_session()
    try:
        # The existing row should be reused: its id is the same, but task_id is new
        # and user_id is now set to the admin.
        reused = session.execute(select(TaskRecord).where(TaskRecord.id == unowned_id)).scalar_one()
    finally:
        session.close()

    assert reused.task_id == new_task_id, 'Reuse branch should have updated task_id'
    assert reused.status == TaskStatus.QUEUED, 'Reused row should be re-queued'
    assert reused.user_id == admin_id, (
        f'Expected NULL user_id to be backfilled to {admin_id}, got {reused.user_id}'
    )


# --- DELETE /media-details/{id}/transcripts tests ---


def _mock_transcript_cancel_side_effects(monkeypatch):
    """Mock external effects of the cancel path: orchestrator cancel + SSE.

    The orchestrator isn't running in tests, so cancel is a safe no-op mock.
    """
    fake_cancel = AsyncMock(return_value='dequeued')
    monkeypatch.setattr('routers.media_details.orch.cancel', fake_cancel)
    monkeypatch.setattr('routers.media_details.publish_status_change', MagicMock())
    return fake_cancel


def _link_transcript_task_to_media(media_id: int, task_status: TaskStatus, task_id: str) -> int:
    """Create a TaskRecord with the given status and link it to a media row's
    transcript_task_record_id. Returns the TaskRecord's integer id.
    """
    session = db.get_sync_session()
    try:
        task = TaskRecord(
            task_id=task_id,
            task_type=TaskType.TRANSCRIPT_GENERATION,
            status=task_status,
            percent_complete=0,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        tr_id = task.id

        md = session.execute(select(MediaDetails).where(MediaDetails.id == media_id)).scalar_one()
        md.transcript_task_record_id = tr_id
        session.add(md)
        session.commit()
    finally:
        session.close()
    return tr_id


def _get_task_status_by_id(tr_id: int) -> TaskStatus:
    session = db.get_sync_session()
    try:
        task = session.execute(select(TaskRecord).where(TaskRecord.id == tr_id)).scalar_one()
        return task.status
    finally:
        session.close()


def test_delete_transcripts_returns_200_with_body_no_active_task(monkeypatch, authenticated_client):
    """Deleting completed transcripts returns 200 with blocks_deleted count.

    Media id=1 has 2 transcript blocks and a COMPLETE transcript task per fixtures.
    The COMPLETE task must NOT be flipped to CANCELLED — it's a completed job.
    """
    _mock_transcript_cancel_side_effects(monkeypatch)

    resp = authenticated_client.delete('/media-details/1/transcripts')
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['blocks_deleted'] == 2
    assert body['task_cancelled'] is False
    assert body['downstream_tasks_cancelled'] == 0

    # Regression guard: the COMPLETE task (id=3) must remain COMPLETE.
    assert _get_task_status_by_id(3) == TaskStatus.COMPLETE


def test_delete_transcripts_cancels_queued_task(monkeypatch, authenticated_client):
    """When transcript task is QUEUED, it is cancelled and marked CANCELLED."""
    _mock_transcript_cancel_side_effects(monkeypatch)

    # Attach a new QUEUED task to media id=2 (fixtures give media 2 one block).
    tr_id = _link_transcript_task_to_media(
        media_id=2, task_status=TaskStatus.QUEUED, task_id='queued-transcript-cancel'
    )

    resp = authenticated_client.delete('/media-details/2/transcripts')
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['task_cancelled'] is True
    assert body['blocks_deleted'] == 1  # media 2 had one pre-existing block in fixtures

    # The TaskRecord should now be CANCELLED.
    assert _get_task_status_by_id(tr_id) == TaskStatus.CANCELLED


def test_delete_transcripts_cancels_in_progress_task(monkeypatch, authenticated_client):
    """When transcript task is IN_PROGRESS, it is terminated and marked CANCELLED.

    This is the data-loss scenario: a long-running transcript may have written
    partial blocks before the user cancelled. Those partials should be removed.
    """
    _mock_transcript_cancel_side_effects(monkeypatch)

    tr_id = _link_transcript_task_to_media(
        media_id=2, task_status=TaskStatus.IN_PROGRESS, task_id='in-progress-transcript-cancel'
    )

    resp = authenticated_client.delete('/media-details/2/transcripts')
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['task_cancelled'] is True
    assert body['blocks_deleted'] == 1

    assert _get_task_status_by_id(tr_id) == TaskStatus.CANCELLED


def test_delete_transcripts_leaves_completed_task_status_intact(monkeypatch, authenticated_client):
    """A COMPLETE transcript task must NOT be flipped to CANCELLED when blocks are deleted.

    This is the regression guard against the latent DELETE /tasks/{task_id} race
    that would wipe a completed transcript. Our new endpoint avoids this by
    only cancelling tasks in {QUEUED, IN_PROGRESS, POSTPROCESSING, RETRY}.
    """
    _mock_transcript_cancel_side_effects(monkeypatch)

    # Media id=1 is pre-linked to COMPLETE task id=3 via fixtures.
    resp = authenticated_client.delete('/media-details/1/transcripts')
    assert resp.status_code == 200
    assert resp.json()['task_cancelled'] is False

    assert _get_task_status_by_id(3) == TaskStatus.COMPLETE


def test_delete_transcripts_clears_media_transcript_task_record_link(
    monkeypatch, authenticated_client
):
    """After deleting transcripts, MediaDetails.transcript_task_record_id must be NULL.

    Without this reset, the Downloads table serializer still sees the old
    (COMPLETE or CANCELLED) TaskRecord via the eager join and keeps rendering
    the wrong transcript icon. Clearing the FK lets the UI fall back to the
    'generate transcript' button as if no transcript had ever been created.
    The TaskRecord row itself is preserved for history in the Tasks tab.
    """
    _mock_transcript_cancel_side_effects(monkeypatch)

    # Media id=1 is pre-linked to COMPLETE task id=3 via fixtures.
    resp = authenticated_client.delete('/media-details/1/transcripts')
    assert resp.status_code == 200

    session = db.get_sync_session()
    try:
        md = session.execute(select(MediaDetails).where(MediaDetails.id == 1)).scalar_one()
        assert md.transcript_task_record_id is None
    finally:
        session.close()

    # The historical TaskRecord row still exists — we only clear the link.
    assert _get_task_status_by_id(3) == TaskStatus.COMPLETE


def test_delete_transcripts_clears_link_after_cancelling_active_task(
    monkeypatch, authenticated_client
):
    """Cancelling an in-progress transcript must also null the FK so the UI
    shows the 'generate transcript' button instead of the CANCELLED retry icon."""
    _mock_transcript_cancel_side_effects(monkeypatch)

    tr_id = _link_transcript_task_to_media(
        media_id=2,
        task_status=TaskStatus.IN_PROGRESS,
        task_id='in-progress-clear-link',
    )

    resp = authenticated_client.delete('/media-details/2/transcripts')
    assert resp.status_code == 200
    assert resp.json()['task_cancelled'] is True

    session = db.get_sync_session()
    try:
        md = session.execute(select(MediaDetails).where(MediaDetails.id == 2)).scalar_one()
        assert md.transcript_task_record_id is None
    finally:
        session.close()

    # Historical record remains, flipped to CANCELLED.
    assert _get_task_status_by_id(tr_id) == TaskStatus.CANCELLED


def test_delete_transcripts_no_task_no_blocks(monkeypatch, authenticated_client):
    """When there's nothing to remove, endpoint still returns 200 with zero counts."""
    _mock_transcript_cancel_side_effects(monkeypatch)

    # Media id=2 has 1 block and no transcript task. First call removes the block.
    first = authenticated_client.delete('/media-details/2/transcripts')
    assert first.status_code == 200
    assert first.json()['blocks_deleted'] == 1
    assert first.json()['task_cancelled'] is False

    # Second call: nothing left to remove.
    second = authenticated_client.delete('/media-details/2/transcripts')
    assert second.status_code == 200
    body = second.json()
    assert body['blocks_deleted'] == 0
    assert body['task_cancelled'] is False
    assert body['downstream_tasks_cancelled'] == 0


def test_delete_transcripts_rejects_non_owner(monkeypatch, authenticated_client):
    """Non-owner users cannot delete or cancel another user's transcripts."""
    _mock_transcript_cancel_side_effects(monkeypatch)

    _admin_id, _user2_id, client2 = _setup_two_users(authenticated_client)

    # user2 has no access/ownership of media id=1, which is owned by testadmin.
    # check_media_owner_or_raise returns 404 (not 403) to avoid leaking existence.
    resp = client2.delete('/media-details/1/transcripts')
    assert resp.status_code == 404, resp.text

    # Verify media 1's blocks are still present.
    session = db.get_sync_session()
    try:
        from models import TranscriptBlock

        blocks = (
            session.execute(select(TranscriptBlock).where(TranscriptBlock.media_details_id == 1))
            .scalars()
            .all()
        )
        assert len(blocks) == 2, 'Non-owner attempt should not have deleted any blocks'
    finally:
        session.close()
