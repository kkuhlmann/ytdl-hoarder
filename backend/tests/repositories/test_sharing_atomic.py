"""Tests for atomic share/unshare cascades (entity access + sourced MediaAccess in one txn)."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from database import db
from models import MediaAccess, SourceType, User
from repositories import playlist_access as pa_repo
from repositories import playlists as playlists_repo
from repositories import sharing
from repositories import subscription_access as sa_repo


async def _create_user(username: str) -> int:
    async with db.get_async_session() as session:
        user = User(username=username, password_hash='x', is_admin=False, is_approved=True)
        session.add(user)
        await session.flush()
        return user.id


async def _media_access_rows(user_id: int) -> list[MediaAccess]:
    async with db.get_async_session() as session:
        result = await session.execute(select(MediaAccess).where(MediaAccess.user_id == user_id))
        return list(result.scalars().all())


async def test_share_playlist_grants_entity_and_media_rows(test_database):
    uid = await _create_user('share-happy')
    playlist = await playlists_repo.create_playlist('Atomic Share')

    inserted = await sharing.share_playlist_with_users([uid], playlist.id, [1, 2])

    assert inserted == 2
    assert await pa_repo.has_access(uid, playlist.id)
    rows = await _media_access_rows(uid)
    assert {r.media_details_id for r in rows} == {1, 2}
    assert all(r.source_type == SourceType.PLAYLIST for r in rows)
    assert all(r.source_id == playlist.id for r in rows)


async def test_share_playlist_rolls_back_on_mid_cascade_failure(test_database):
    """A failure inside the cascade leaves NO partial state (the whole point of atomicity)."""
    uid = await _create_user('share-atomic')
    playlist = await playlists_repo.create_playlist('Rollback Test')

    # media id 999999 doesn't exist → FK violation on the MediaAccess insert,
    # AFTER the PlaylistAccess insert already executed in the same transaction.
    with pytest.raises(IntegrityError):
        await sharing.share_playlist_with_users([uid], playlist.id, [1, 999999])

    assert not await pa_repo.has_access(uid, playlist.id)
    assert await _media_access_rows(uid) == []


async def test_unshare_playlist_removes_entity_and_media_rows(test_database):
    uid = await _create_user('unshare-happy')
    playlist = await playlists_repo.create_playlist('Atomic Unshare')
    await sharing.share_playlist_with_users([uid], playlist.id, [1, 2])

    removed, revoked = await sharing.unshare_playlist_for_user(uid, playlist.id)

    assert removed is True
    assert revoked == 2
    assert not await pa_repo.has_access(uid, playlist.id)
    assert await _media_access_rows(uid) == []


async def test_unshare_playlist_without_access_is_noop(test_database):
    """No PlaylistAccess row → (False, 0) and nothing deleted (matches old 404-first behavior)."""
    uid = await _create_user('unshare-noop')
    playlist = await playlists_repo.create_playlist('Noop Unshare')

    assert await sharing.unshare_playlist_for_user(uid, playlist.id) == (False, 0)


async def test_share_and_unshare_subscription(test_database):
    """Subscription variants mirror the playlist behavior (seeded subscription id 1)."""
    uid = await _create_user('share-sub')

    inserted = await sharing.share_subscription_with_users([uid], 1, [1, 2])
    assert inserted == 2
    assert await sa_repo.has_access(uid, 1)
    rows = await _media_access_rows(uid)
    assert all(r.source_type == SourceType.SUBSCRIPTION for r in rows)

    removed, revoked = await sharing.unshare_subscription_for_user(uid, 1)
    assert (removed, revoked) == (True, 2)
    assert await _media_access_rows(uid) == []
