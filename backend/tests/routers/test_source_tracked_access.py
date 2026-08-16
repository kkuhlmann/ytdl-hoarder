"""Tests for source-tracked media access.

Verifies that sharing playlists/subscriptions cascades MediaAccess rows with proper
source_type/source_id tracking, and that revocation works at the correct scope.
"""

from sqlmodel import select

from database import db
from models import (
    DownloadJob,
    JobType,
    MediaAccess,
    MediaType,
    SourceType,
    Subscription,
)


def _setup_two_users(client):
    """Register admin (first user) + second user. Return (admin_id, user2_id, client2)."""
    from fastapi.testclient import TestClient

    from main import app

    # admin is already registered by authenticated_client fixture
    admin_resp = client.get('/auth/users')
    admin_user = next(u for u in admin_resp.json() if u['username'] == 'testadmin')
    admin_id = admin_user['id']

    # Register + approve second user
    reg_resp = client.post('/auth/register', json={'username': 'user2', 'password': 'pass123'})
    user2_id = reg_resp.json()['id']
    client.post(f'/auth/users/{user2_id}/approve')

    # Create client for second user
    client2 = TestClient(app)
    client2.post('/auth/login', json={'username': 'user2', 'password': 'pass123'})

    return admin_id, user2_id, client2


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


def _count_all_media_access_for_user(user_id, source_type=None, source_id=None):
    """Count all MediaAccess rows for a user, optionally filtered by source."""
    session = db.get_sync_session()
    try:
        conditions = [MediaAccess.user_id == user_id]
        if source_type is not None:
            conditions.append(MediaAccess.source_type == source_type)
        if source_id is not None:
            conditions.append(MediaAccess.source_id == source_id)

        stmt = select(MediaAccess).where(*conditions)
        result = session.execute(stmt)
        return len(result.scalars().all())
    finally:
        session.close()


# ============================================================
# Playlist sharing cascades
# ============================================================


def test_share_playlist_grants_media_access(authenticated_client):
    """Sharing a playlist creates playlist-sourced MediaAccess rows for all media in it."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Create a playlist and add media 1 and 2
    create_resp = authenticated_client.post('/playlists', json={'name': 'Share Test'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 2})

    # user2 should NOT have access to media yet
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 0
    assert _count_media_access(user2_id, 2, SourceType.PLAYLIST, playlist_id) == 0

    # Share playlist with user2
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})

    # user2 should now have playlist-sourced access to both media items
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1
    assert _count_media_access(user2_id, 2, SourceType.PLAYLIST, playlist_id) == 1

    # user2 should be able to see the playlist
    resp = client2.get(f'/playlists/{playlist_id}')
    assert resp.status_code == 200

    # user2 should be able to access the media
    resp = client2.get('/media-details/1')
    assert resp.status_code == 200


def test_unshare_playlist_revokes_media_access(authenticated_client):
    """Unsharing a playlist removes all playlist-sourced MediaAccess for that user."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Create playlist, add media, share
    create_resp = authenticated_client.post('/playlists', json={'name': 'Unshare Test'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})

    # Verify access exists
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1

    # Unshare
    authenticated_client.delete(f'/playlists/{playlist_id}/share/{user2_id}')

    # Access should be revoked
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 0

    # user2 should NOT be able to access the media anymore
    resp = client2.get('/media-details/1')
    assert resp.status_code == 404


def test_shared_user_removes_playlist_loses_media_access(authenticated_client):
    """When a shared user 'deletes' a playlist, they lose playlist-sourced media access."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Create playlist, add media, share
    create_resp = authenticated_client.post('/playlists', json={'name': 'User Remove Test'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1

    # user2 "deletes" (removes from their view) the playlist
    resp = client2.delete(f'/playlists/{playlist_id}')
    assert resp.status_code == 204

    # Playlist should still exist for owner
    resp = authenticated_client.get(f'/playlists/{playlist_id}')
    assert resp.status_code == 200

    # user2's media access should be revoked
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 0


def test_add_media_to_shared_playlist_grants_access(authenticated_client):
    """Adding media to an already-shared playlist grants access to shared users."""
    _admin_id, user2_id, _client2 = _setup_two_users(authenticated_client)

    # Create playlist and share (empty)
    create_resp = authenticated_client.post('/playlists', json={'name': 'Add Media Test'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})

    # No media access yet
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 0

    # Add media to the shared playlist
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})

    # user2 should now have access
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1


def test_remove_media_from_shared_playlist_revokes_access(authenticated_client):
    """Removing media from a shared playlist revokes access for shared users."""
    _admin_id, user2_id, _client2 = _setup_two_users(authenticated_client)

    # Create playlist, add media, share
    create_resp = authenticated_client.post('/playlists', json={'name': 'Remove Media Test'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1

    # Remove media from playlist
    authenticated_client.delete(f'/playlists/{playlist_id}/media/1')

    # Access should be revoked
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 0


def test_same_media_in_two_playlists_removing_one_preserves_other(authenticated_client):
    """If same media is in two shared playlists, removing one preserves the other."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Create two playlists, both with media 1, both shared
    resp1 = authenticated_client.post('/playlists', json={'name': 'Playlist A'})
    playlist_a = resp1.json()['id']
    resp2 = authenticated_client.post('/playlists', json={'name': 'Playlist B'})
    playlist_b = resp2.json()['id']

    authenticated_client.post(f'/playlists/{playlist_a}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_b}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_a}/share', json={'user_id': user2_id})
    authenticated_client.post(f'/playlists/{playlist_b}/share', json={'user_id': user2_id})

    # user2 has access from both playlists
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_a) == 1
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_b) == 1

    # Unshare playlist A
    authenticated_client.delete(f'/playlists/{playlist_a}/share/{user2_id}')

    # Playlist A access gone, Playlist B access preserved
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_a) == 0
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_b) == 1

    # user2 can still access media 1 via playlist B
    resp = client2.get('/media-details/1')
    assert resp.status_code == 200


def test_owner_deletes_playlist_cleans_up_access(authenticated_client):
    """Owner deleting a playlist atomically removes all playlist-sourced MediaAccess."""
    _admin_id, user2_id, _client2 = _setup_two_users(authenticated_client)

    # Create playlist, add media, share
    create_resp = authenticated_client.post('/playlists', json={'name': 'Owner Delete Test'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1

    # Owner deletes the playlist
    resp = authenticated_client.delete(f'/playlists/{playlist_id}')
    assert resp.status_code == 204

    # All playlist-sourced access should be cleaned up
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 0


# ============================================================
# Subscription sharing cascades
# ============================================================


def _create_subscription_with_media(client):
    """Create a subscription with a download_job linked to existing media.

    Returns subscription_id.
    """
    session = db.get_sync_session()
    try:
        # Get the admin user's ID
        users_resp = client.get('/auth/users')
        admin_id = next(u for u in users_resp.json() if u['username'] == 'testadmin')['id']

        # Create a subscription directly in DB
        sub = Subscription(
            url='https://www.youtube.com/@RickAstleyYT',
            channel='Test Channel',
            audio_only=True,
            media_type=MediaType.AUDIO,
            job_type=JobType.CHANNEL_SUBSCRIPTION,
            user_id=admin_id,
        )
        session.add(sub)
        session.commit()
        session.refresh(sub)

        # Link existing download_job 1 to this subscription and media 1
        stmt = select(DownloadJob).where(DownloadJob.id == 1)
        dj = session.execute(stmt).scalar_one()
        dj.subscription_id = sub.id
        session.commit()

        return sub.id
    finally:
        session.close()


def test_share_subscription_grants_retroactive_media_access(authenticated_client):
    """Sharing a subscription grants access to all existing media from that subscription."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)
    sub_id = _create_subscription_with_media(authenticated_client)

    # user2 should NOT have subscription-sourced access yet
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 0

    # Share subscription with user2
    authenticated_client.post(f'/subscriptions/{sub_id}/share', json={'user_id': user2_id})

    # user2 should now have subscription-sourced access to media 1
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 1

    # user2 can access the media
    resp = client2.get('/media-details/1')
    assert resp.status_code == 200


def test_unshare_subscription_revokes_media_access(authenticated_client):
    """Unsharing a subscription revokes all subscription-sourced MediaAccess."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)
    sub_id = _create_subscription_with_media(authenticated_client)

    # Share then unshare
    authenticated_client.post(f'/subscriptions/{sub_id}/share', json={'user_id': user2_id})
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 1

    authenticated_client.delete(f'/subscriptions/{sub_id}/share/{user2_id}')

    # Access revoked
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 0
    resp = client2.get('/media-details/1')
    assert resp.status_code == 404


def test_shared_user_removes_subscription_loses_media_access(authenticated_client):
    """When a shared user 'deletes' a subscription, they lose subscription-sourced access."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)
    sub_id = _create_subscription_with_media(authenticated_client)

    # Share with user2
    authenticated_client.post(f'/subscriptions/{sub_id}/share', json={'user_id': user2_id})
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 1

    # user2 "deletes" (removes from their view)
    resp = client2.delete(f'/subscriptions/{sub_id}')
    assert resp.status_code == 204

    # Subscription should still exist for owner
    resp = authenticated_client.get(f'/subscriptions/{sub_id}')
    assert resp.status_code == 200

    # user2's media access should be revoked
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 0


def test_owner_deletes_subscription_cleans_up_access(authenticated_client):
    """Owner deleting a subscription atomically removes subscription-sourced MediaAccess."""
    _admin_id, user2_id, _client2 = _setup_two_users(authenticated_client)
    sub_id = _create_subscription_with_media(authenticated_client)

    # Share with user2
    authenticated_client.post(f'/subscriptions/{sub_id}/share', json={'user_id': user2_id})
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 1

    # Owner deletes the subscription
    resp = authenticated_client.delete(f'/subscriptions/{sub_id}')
    assert resp.status_code == 204

    # All subscription-sourced access cleaned up
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 0


# ============================================================
# Media deletion scoped behavior
# ============================================================


def test_nonowner_with_direct_access_removes_direct_only(authenticated_client):
    """Non-owner with direct access deletes media → only direct access row removed."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Share media 1 directly with user2
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})
    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 1

    # user2 deletes the media → should only remove their direct access
    resp = client2.delete('/media-details/1')
    assert resp.status_code == 204

    # Direct access removed
    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 0

    # Media still exists for owner
    resp = authenticated_client.get('/media-details/1')
    assert resp.status_code == 200


def test_nonowner_with_direct_and_shared_access_keeps_shared(authenticated_client):
    """Non-owner with direct + playlist access: delete removes only direct, keeps shared."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Share media directly
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})

    # Also share via playlist
    create_resp = authenticated_client.post('/playlists', json={'name': 'Multi Source'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})

    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 1
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1

    # user2 deletes the media → only direct access removed
    resp = client2.delete('/media-details/1')
    assert resp.status_code == 204

    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 0
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1

    # user2 can still access via playlist
    resp = client2.get('/media-details/1')
    assert resp.status_code == 200


def test_nonowner_with_only_playlist_access_delete_returns_403(authenticated_client):
    """Non-owner with only playlist access tries to delete media → 403."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Share via playlist only (no direct access)
    create_resp = authenticated_client.post('/playlists', json={'name': 'Shared Only'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})

    # Verify user2 has ONLY playlist access
    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 0
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1

    # user2 tries to delete → 403 (must remove at parent scope)
    resp = client2.delete('/media-details/1')
    assert resp.status_code == 403
    assert 'shared playlist or subscription' in resp.json()['detail']

    # Playlist access should be unchanged
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1


def test_nonowner_cannot_hard_delete(authenticated_client):
    """Non-owner cannot hard-delete media, even with access."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Share directly
    authenticated_client.post('/media-details/2/share', json={'user_id': user2_id})

    # Soft delete as owner first (required for hard delete)
    authenticated_client.delete('/media-details/2')

    # user2 tries to hard delete → 404
    resp = client2.delete('/media-details/2/hard')
    assert resp.status_code == 404


def test_nonowner_cannot_delete_transcripts(authenticated_client):
    """Non-owner cannot delete transcripts."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)

    # Share directly
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})

    # user2 tries to delete transcripts → 404
    resp = client2.delete('/media-details/1/transcripts')
    assert resp.status_code == 404


# ============================================================
# Multiple source types
# ============================================================


def test_multiple_sources_independent(authenticated_client):
    """Access from direct, playlist, and subscription are independent rows."""
    _admin_id, user2_id, client2 = _setup_two_users(authenticated_client)
    sub_id = _create_subscription_with_media(authenticated_client)

    # Share directly
    authenticated_client.post('/media-details/1/share', json={'user_id': user2_id})

    # Share via playlist
    create_resp = authenticated_client.post('/playlists', json={'name': 'Multi Source Test'})
    playlist_id = create_resp.json()['id']
    authenticated_client.post(f'/playlists/{playlist_id}/media', json={'media_details_id': 1})
    authenticated_client.post(f'/playlists/{playlist_id}/share', json={'user_id': user2_id})

    # Share via subscription
    authenticated_client.post(f'/subscriptions/{sub_id}/share', json={'user_id': user2_id})

    # user2 should have three separate access rows
    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 1
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 1

    # Revoke direct → still has playlist + subscription
    resp = client2.delete('/media-details/1')  # removes direct access
    assert resp.status_code == 204
    assert _count_media_access(user2_id, 1, SourceType.DIRECT, 0) == 0
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 1
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 1

    # Revoke playlist → still has subscription
    authenticated_client.delete(f'/playlists/{playlist_id}/share/{user2_id}')
    assert _count_media_access(user2_id, 1, SourceType.PLAYLIST, playlist_id) == 0
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 1

    # user2 can still access via subscription
    resp = client2.get('/media-details/1')
    assert resp.status_code == 200

    # Revoke subscription → no access
    authenticated_client.delete(f'/subscriptions/{sub_id}/share/{user2_id}')
    assert _count_media_access(user2_id, 1, SourceType.SUBSCRIPTION, sub_id) == 0

    # user2 can no longer access
    resp = client2.get('/media-details/1')
    assert resp.status_code == 404
