"""Tests for bulk add-to-playlist with concurrent positioning."""

from sqlmodel import select

from database import db
from models import MediaDetails, MediaType, PlaylistMedia, TaskStatus
from repositories import playlists


async def _all_media_ids_after_inserting(extra: int) -> list[int]:
    """Insert `extra` COMPLETE media rows and return every media id (seed + new)."""
    async with db.get_async_session() as session:
        for i in range(extra):
            session.add(
                MediaDetails(
                    url=f'https://example.com/watch?v=bulk{i}',
                    media_type=MediaType.AUDIO,
                    channel='bulk-channel',
                    title=f'bulk media {i}',
                    status=TaskStatus.COMPLETE,
                )
            )
        await session.commit()
    async with db.get_async_session() as session:
        rows = (
            (await session.execute(select(MediaDetails.id).order_by(MediaDetails.id)))
            .scalars()
            .all()
        )
        return list(rows)


async def test_add_media_bulk_assigns_unique_sequential_positions(test_database):
    """50 media added in one call get contiguous, unique positions 1..N (no race)."""
    media_ids = await _all_media_ids_after_inserting(48)  # 48 + 2 seed = 50
    assert len(media_ids) == 50

    playlist = await playlists.create_playlist('Bulk Positions')
    result = await playlists.add_media_bulk(playlist.id, media_ids)

    assert result['added'] == 50
    assert result['already_present'] == 0
    assert result['invalid'] == 0

    async with db.get_async_session() as session:
        positions = (
            (
                await session.execute(
                    select(PlaylistMedia.position).where(PlaylistMedia.playlist_id == playlist.id)
                )
            )
            .scalars()
            .all()
        )

    assert len(positions) == 50
    assert sorted(positions) == list(range(1, 51))
    assert len(set(positions)) == 50  # all unique


async def test_add_media_bulk_is_idempotent(test_database):
    """Re-adding the same media reports them as already present, adds nothing."""
    media_ids = await _all_media_ids_after_inserting(3)
    playlist = await playlists.create_playlist('Idempotent')

    first = await playlists.add_media_bulk(playlist.id, media_ids)
    assert first['added'] == len(media_ids)

    second = await playlists.add_media_bulk(playlist.id, media_ids)
    assert second['added'] == 0
    assert second['already_present'] == len(media_ids)
    assert second['invalid'] == 0


async def test_add_media_bulk_mixed_input(test_database):
    """De-dupes input, skips already-present and non-existent ids, counts each bucket."""
    all_ids = await _all_media_ids_after_inserting(3)  # e.g. [1, 2, 3, 4, 5]
    playlist = await playlists.create_playlist('Mixed')

    # Pre-populate with the first two media.
    await playlists.add_media_bulk(playlist.id, all_ids[:2])

    # Request: two already-present, one new (listed twice), one invalid id.
    invalid_id = 999_999
    request_ids = [all_ids[0], all_ids[1], all_ids[2], all_ids[2], invalid_id]
    result = await playlists.add_media_bulk(playlist.id, request_ids)

    assert result['added'] == 1
    assert result['added_media_ids'] == [all_ids[2]]
    assert result['already_present'] == 2
    assert result['invalid'] == 1


async def test_add_media_bulk_missing_playlist_returns_none(test_database):
    """A non-existent playlist id yields None (router maps this to 404)."""
    assert await playlists.add_media_bulk(123_456, [1, 2]) is None
