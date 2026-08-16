from sqlmodel import select

from database import db
from models import (
    MediaDetails,
    MediaRating,
    MediaTag,
    MediaType,
    PlaybackState,
    Tag,
    TaskRecord,
    TaskStatus,
    TaskType,
    User,
)
from repositories import playlists


async def test_remove_media_from_one_playlist(test_database):
    """Media in one playlist is removed and remaining positions shift down."""
    # Create a playlist with 3 items: media 1 at pos 1, media 2 at pos 2, then a third media
    playlist = await playlists.create_playlist('Test Playlist')
    await playlists.add_media_to_playlist(playlist.id, 1, position=1)
    await playlists.add_media_to_playlist(playlist.id, 2, position=2)

    # Remove media 1 from all playlists
    count = await playlists.remove_media_from_all_playlists(1)
    assert count == 1

    # Media 2 should now be at position 1
    media_result = await playlists.get_playlist_media(playlist.id)
    assert media_result['count_records'] == 1
    assert media_result['records'][0]['media_details_id'] == 2
    assert media_result['records'][0]['position'] == 1


async def test_remove_media_from_multiple_playlists(test_database):
    """Media in multiple playlists is removed from all, with positions fixed in each."""
    playlist_a = await playlists.create_playlist('Playlist A')
    playlist_b = await playlists.create_playlist('Playlist B')

    # Add media 1 and 2 to both playlists
    await playlists.add_media_to_playlist(playlist_a.id, 1, position=1)
    await playlists.add_media_to_playlist(playlist_a.id, 2, position=2)
    await playlists.add_media_to_playlist(playlist_b.id, 1, position=1)
    await playlists.add_media_to_playlist(playlist_b.id, 2, position=2)

    # Remove media 1 from all playlists
    count = await playlists.remove_media_from_all_playlists(1)
    assert count == 2

    # Both playlists should have media 2 at position 1
    for pl in [playlist_a, playlist_b]:
        media_result = await playlists.get_playlist_media(pl.id)
        assert media_result['count_records'] == 1
        assert media_result['records'][0]['media_details_id'] == 2
        assert media_result['records'][0]['position'] == 1


async def test_remove_media_not_in_any_playlist(test_database):
    """Removing media that isn't in any playlist returns 0."""
    count = await playlists.remove_media_from_all_playlists(1)
    assert count == 0


async def test_remove_media_updates_playlist_timestamps(test_database):
    """Playlist updated_at is refreshed after removing media."""
    playlist = await playlists.create_playlist('Timestamp Test')
    await playlists.add_media_to_playlist(playlist.id, 1, position=1)

    # Capture the playlist's updated_at before removal
    before = await playlists.get_playlist_by_id(playlist.id)
    before_updated_at = before.updated_at

    # Remove media
    await playlists.remove_media_from_all_playlists(1)

    # updated_at should have changed
    after = await playlists.get_playlist_by_id(playlist.id)
    assert after.updated_at >= before_updated_at


async def test_get_all_playlists_stats_for_full_and_empty_playlists(test_database):
    """One list call returns correct stats for a populated and an empty playlist."""
    async with db.get_async_session() as session:
        session.add_all(
            [
                MediaDetails(
                    url='https://example.com/watch?v=stats1',
                    media_type=MediaType.AUDIO,
                    channel='stats-channel',
                    title='stats media 1',
                    status=TaskStatus.COMPLETE,
                    duration=100.0,
                ),
                MediaDetails(
                    url='https://example.com/watch?v=stats2',
                    media_type=MediaType.AUDIO,
                    channel='stats-channel',
                    title='stats media 2',
                    status=TaskStatus.COMPLETE,
                    duration=250.0,
                ),
            ]
        )
        await session.commit()
    async with db.get_async_session() as session:
        new_ids = (
            (
                await session.execute(
                    select(MediaDetails.id).where(MediaDetails.channel == 'stats-channel')
                )
            )
            .scalars()
            .all()
        )

    full = await playlists.create_playlist('Full Playlist')
    empty = await playlists.create_playlist('Empty Playlist')
    # Seed media id 1 has duration=None — must count toward media_count but add 0 duration
    await playlists.add_media_bulk(full.id, [*new_ids, 1])

    result = await playlists.get_all_playlists()
    by_id = {r['id']: r for r in result['records']}

    assert by_id[full.id]['media_count'] == 3
    assert by_id[full.id]['total_duration'] == 350
    assert by_id[empty.id]['media_count'] == 0
    assert by_id[empty.id]['total_duration'] == 0


async def _seed_media(session, titles: list[str], channel: str) -> None:
    session.add_all(
        [
            MediaDetails(
                url=f'https://example.com/watch?v={channel}-{i}',
                media_type=MediaType.AUDIO,
                channel=channel,
                title=title,
                status=TaskStatus.COMPLETE,
                duration=60.0,
            )
            for i, title in enumerate(titles)
        ]
    )
    await session.commit()


async def _media_ids(channel: str) -> list[int]:
    async with db.get_async_session() as session:
        return list(
            (
                await session.execute(
                    select(MediaDetails.id)
                    .where(MediaDetails.channel == channel)
                    .order_by(MediaDetails.id)
                )
            )
            .scalars()
            .all()
        )


async def test_get_playlist_media_returns_requesting_users_rating_and_tags(test_database):
    """Track records carry the caller's own rating/tags, not another user's."""
    async with db.get_async_session() as session:
        await _seed_media(session, ['parity a', 'parity b'], 'parity-channel')
    ids = await _media_ids('parity-channel')

    playlist = await playlists.create_playlist('Parity')
    await playlists.add_media_bulk(playlist.id, ids)

    async with db.get_async_session() as session:
        session.add_all(
            [
                User(username='owner_p', password_hash='x', is_approved=True),
                User(username='other_p', password_hash='x', is_approved=True),
            ]
        )
        await session.commit()
        owner_id, other_id = (
            (
                await session.execute(
                    select(User.id)
                    .where(User.username.in_(['owner_p', 'other_p']))
                    .order_by(User.username.desc())
                )
            )
            .scalars()
            .all()
        )

    async with db.get_async_session() as session:
        tag = Tag(user_id=owner_id, name='focus')
        session.add(tag)
        await session.flush()
        session.add_all(
            [
                MediaRating(user_id=owner_id, media_details_id=ids[0], rating=4),
                MediaRating(user_id=other_id, media_details_id=ids[0], rating=1),
                MediaTag(user_id=owner_id, media_details_id=ids[0], tag_id=tag.id),
                PlaybackState(user_id=owner_id, media_details_id=ids[0], playback_position=30.0),
            ]
        )
        await session.commit()

    result = await playlists.get_playlist_media(playlist.id, user_id=owner_id)
    first = next(r for r in result['records'] if r['media_details_id'] == ids[0])

    assert first['rating'] == 4
    assert [t['name'] for t in first['tags']] == ['focus']
    assert first['playback_position'] == 30.0
    # Full media fields, not just the join columns
    assert first['url'].endswith('parity-channel-0')
    assert first['title'] == 'parity a'
    # Join fields, with the PK deliberately named playlist_media_id
    assert first['position'] == 1
    assert first['playlist_id'] == playlist.id
    assert 'playlist_media_id' in first

    other = await playlists.get_playlist_media(playlist.id, user_id=other_id)
    other_first = next(r for r in other['records'] if r['media_details_id'] == ids[0])
    assert other_first['rating'] == 1
    assert other_first['tags'] == []
    assert other_first['playback_position'] is None


async def test_get_playlist_media_light_skips_per_user_enrichment(test_database):
    """light=True omits ratings/tags/playback — the media player never reads them.

    The media here deliberately has a linked task record. The shared serializer
    reads record.download_task_record unconditionally, and SQLAlchemy silently
    skips the lazy load when the FK is NULL — so seeding without one lets a
    missing eager load pass here and blow up against real data.
    """
    async with db.get_async_session() as session:
        await _seed_media(session, ['light a'], 'light-channel')
    ids = await _media_ids('light-channel')

    async with db.get_async_session() as session:
        task = TaskRecord(
            task_id='light-task',
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.COMPLETE,
            percent_complete=100,
        )
        session.add(task)
        await session.flush()
        media = await session.get(MediaDetails, ids[0])
        media.download_task_record_id = task.id
        media.transcript_task_record_id = task.id
        await session.commit()

    playlist = await playlists.create_playlist('Light')
    await playlists.add_media_bulk(playlist.id, ids)

    async with db.get_async_session() as session:
        session.add(User(username='light_user', password_hash='x', is_approved=True))
        await session.commit()
        user_id = (
            await session.execute(select(User.id).where(User.username == 'light_user'))
        ).scalar_one()

    async with db.get_async_session() as session:
        session.add(MediaRating(user_id=user_id, media_details_id=ids[0], rating=5))
        await session.commit()

    light = await playlists.get_playlist_media(playlist.id, user_id=user_id, light=True)
    assert light['records'][0]['rating'] is None
    assert light['records'][0]['tags'] == []
    # Basic fields the queue does read are still present
    assert light['records'][0]['title'] == 'light a'
    assert light['records'][0]['position'] == 1

    full = await playlists.get_playlist_media(playlist.id, user_id=user_id)
    assert full['records'][0]['rating'] == 5


async def test_include_playback_adds_position_to_a_light_fetch(test_database):
    """A resuming player queue needs positions without paying for ratings/tags.

    Both halves matter: without include_playback the queue silently starts every
    track at 0, and if it re-enabled the whole enrichment it would undo what
    light is for.
    """
    async with db.get_async_session() as session:
        await _seed_media(session, ['resume a'], 'resume-channel')
    ids = await _media_ids('resume-channel')

    playlist = await playlists.create_playlist('Resume')
    await playlists.add_media_bulk(playlist.id, ids)

    async with db.get_async_session() as session:
        session.add(User(username='resume_user', password_hash='x', is_approved=True))
        await session.commit()
        user_id = (
            await session.execute(select(User.id).where(User.username == 'resume_user'))
        ).scalar_one()

    async with db.get_async_session() as session:
        tag = Tag(user_id=user_id, name='later')
        session.add(tag)
        await session.flush()
        session.add_all(
            [
                MediaRating(user_id=user_id, media_details_id=ids[0], rating=5),
                MediaTag(user_id=user_id, media_details_id=ids[0], tag_id=tag.id),
                PlaybackState(user_id=user_id, media_details_id=ids[0], playback_position=42.0),
            ]
        )
        await session.commit()

    light = await playlists.get_playlist_media(playlist.id, user_id=user_id, light=True)
    assert light['records'][0]['playback_position'] is None

    resuming = await playlists.get_playlist_media(
        playlist.id, user_id=user_id, light=True, include_playback=True
    )
    assert resuming['records'][0]['playback_position'] == 42.0
    assert resuming['records'][0]['rating'] is None
    assert resuming['records'][0]['tags'] == []


async def test_get_all_playlists_returns_up_to_four_samples_in_position_order(test_database):
    """sample_media_ids caps at 4 and follows playlist order, not recency."""
    async with db.get_async_session() as session:
        await _seed_media(session, [f'sample {i}' for i in range(6)], 'sample-channel')
    ids = await _media_ids('sample-channel')

    playlist = await playlists.create_playlist('Samples')
    await playlists.add_media_bulk(playlist.id, ids)
    empty = await playlists.create_playlist('No Samples')

    result = await playlists.get_all_playlists()
    by_id = {r['id']: r for r in result['records']}

    assert by_id[playlist.id]['sample_media_ids'] == ids[:4]
    assert by_id[empty.id]['sample_media_ids'] == []


async def test_remove_media_bulk_leaves_positions_contiguous(test_database):
    """Bulk removal renumbers to 1..N — the reorder arrows depend on contiguity."""
    async with db.get_async_session() as session:
        await _seed_media(session, [f'bulk {i}' for i in range(5)], 'bulk-channel')
    ids = await _media_ids('bulk-channel')

    playlist = await playlists.create_playlist('Bulk Remove')
    await playlists.add_media_bulk(playlist.id, ids)

    # Remove from the middle and both ends at once
    removed = await playlists.remove_media_bulk(playlist.id, [ids[0], ids[2], ids[4]])
    assert removed == 3

    result = await playlists.get_playlist_media(playlist.id)
    positions = [r['position'] for r in result['records']]
    assert positions == [1, 2]
    assert [r['media_details_id'] for r in result['records']] == [ids[1], ids[3]]

    assert await playlists.remove_media_bulk(playlist.id, []) == 0
    assert await playlists.remove_media_bulk(playlist.id, [999999]) == 0


async def test_get_playlist_media_sorting(test_database):
    """Tracks can be sorted by a MediaDetails column, defaulting to position."""
    async with db.get_async_session() as session:
        session.add_all(
            [
                MediaDetails(
                    url='https://example.com/watch?v=sort-b',
                    media_type=MediaType.AUDIO,
                    channel='sort-channel',
                    title='B second',
                    status=TaskStatus.COMPLETE,
                    duration=300.0,
                ),
                MediaDetails(
                    url='https://example.com/watch?v=sort-a',
                    media_type=MediaType.AUDIO,
                    channel='sort-channel',
                    title='A first',
                    status=TaskStatus.COMPLETE,
                    duration=100.0,
                ),
            ]
        )
        await session.commit()
    ids = await _media_ids('sort-channel')

    playlist = await playlists.create_playlist('Sorting')
    await playlists.add_media_bulk(playlist.id, ids)

    default = await playlists.get_playlist_media(playlist.id)
    assert [r['position'] for r in default['records']] == [1, 2]

    by_duration = await playlists.get_playlist_media(
        playlist.id, sort_by='duration', sort_direction='asc'
    )
    assert [r['duration'] for r in by_duration['records']] == [100.0, 300.0]

    by_duration_desc = await playlists.get_playlist_media(
        playlist.id, sort_by='duration', sort_direction='desc'
    )
    assert [r['duration'] for r in by_duration_desc['records']] == [300.0, 100.0]
