"""Tests for bulk MediaAccess grant primitives (single INSERT ... ON CONFLICT DO NOTHING)."""

from sqlmodel import select

from database import db
from models import MediaAccess, SourceType, User
from repositories import media_access as ma_repo


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


async def test_add_access_bulk_inserts_cross_product(test_database):
    """Bulk grant inserts one row per (user, media) pair."""
    uid_a = await _create_user('bulk-a')
    uid_b = await _create_user('bulk-b')

    inserted = await ma_repo.add_access_bulk(
        [uid_a, uid_b], [1, 2], source_type=SourceType.PLAYLIST, source_id=5
    )

    assert inserted == 4
    assert len(await _media_access_rows(uid_a)) == 2
    assert len(await _media_access_rows(uid_b)) == 2


async def test_add_access_bulk_is_idempotent(test_database):
    """Re-running the same bulk grant inserts nothing and raises no error."""
    uid = await _create_user('bulk-idem')

    first = await ma_repo.add_access_bulk([uid], [1, 2])
    second = await ma_repo.add_access_bulk([uid], [1, 2])

    assert first == 2
    assert second == 0
    assert len(await _media_access_rows(uid)) == 2


async def test_add_access_bulk_skips_existing_rows(test_database):
    """Rows already granted via single add_access are skipped, new ones inserted."""
    uid = await _create_user('bulk-partial')
    await ma_repo.add_access(uid, 1, source_type=SourceType.SUBSCRIPTION, source_id=9)

    inserted = await ma_repo.add_access_bulk(
        [uid], [1, 2], source_type=SourceType.SUBSCRIPTION, source_id=9
    )

    assert inserted == 1
    assert len(await _media_access_rows(uid)) == 2


async def test_add_access_bulk_dedupes_input_and_handles_empty(test_database):
    """Duplicate ids in input collapse to one row; empty input is a no-op."""
    uid = await _create_user('bulk-dupes')

    assert await ma_repo.add_access_bulk([uid, uid], [1, 1]) == 1
    assert await ma_repo.add_access_bulk([], [1]) == 0
    assert await ma_repo.add_access_bulk([uid], []) == 0


def test_sync_add_access_bulk(test_database):
    """Sync variant inserts and is idempotent (job-body path)."""
    with db.sync_session() as session:
        user = User(username='bulk-sync', password_hash='x', is_admin=False, is_approved=True)
        session.add(user)
        session.flush()
        uid = user.id

    first = ma_repo.sync_add_access_bulk(
        [uid], [1, 2], source_type=SourceType.SUBSCRIPTION, source_id=1
    )
    second = ma_repo.sync_add_access_bulk(
        [uid], [1, 2], source_type=SourceType.SUBSCRIPTION, source_id=1
    )

    assert first == 2
    assert second == 0


async def test_entity_add_access_bulk_idempotent(test_database):
    """Factory-generated bulk grant inserts once per user, skipping existing rows."""
    from repositories import playlist_access as pa_repo
    from repositories import playlists as playlists_repo

    uid_a = await _create_user('entity-a')
    uid_b = await _create_user('entity-b')
    playlist = await playlists_repo.create_playlist('Bulk Entity Test')

    await pa_repo.add_access(uid_a, playlist.id)

    inserted = await pa_repo.add_access_bulk([uid_a, uid_b, uid_b], playlist.id)

    assert inserted == 1  # uid_a existed, uid_b deduped to one row
    assert await pa_repo.has_access(uid_a, playlist.id)
    assert await pa_repo.has_access(uid_b, playlist.id)
    assert await pa_repo.add_access_bulk([], playlist.id) == 0
