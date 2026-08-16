"""Tests for media grouping aggregation (get_media_groups)."""

from datetime import datetime

from database import db
from models import MediaDetails, MediaTag, MediaType, Tag, TaskStatus, User
from repositories import media_details


async def _add(
    url,
    *,
    channel=None,
    media_type=MediaType.VIDEO,
    duration=None,
    file_size=None,
    release=None,
    downloaded=None,
    created=None,
    status=TaskStatus.COMPLETE,
):
    """Helper to insert a MediaDetails row and return its id."""
    md = MediaDetails(
        url=url,
        media_type=media_type,
        channel=channel,
        title=url,
        duration=duration,
        file_size_bytes=file_size,
        release_timestamp=release,
        downloaded_at=downloaded,
        status=status,
    )
    if created is not None:
        md.created_at = created
    saved = await media_details.upsert_media_details(md)
    return saved.id


def _find(groups, key):
    return next((g for g in groups if g['key'] == key), None)


async def test_group_by_channel_counts_and_aggregates(test_database):
    await _add(
        'u://v1', channel='Veritasium', media_type=MediaType.VIDEO, duration=100, file_size=1000
    )
    await _add(
        'u://v2', channel='Veritasium', media_type=MediaType.VIDEO, duration=200, file_size=2000
    )
    await _add(
        'u://v3', channel='Veritasium', media_type=MediaType.AUDIO, duration=50, file_size=500
    )

    result = await media_details.get_media_groups(group_by='channel')
    groups = result['groups']

    ver = _find(groups, 'Veritasium')
    assert ver is not None
    assert ver['count'] == 3
    assert ver['total_duration'] == 350
    assert ver['total_size_bytes'] == 3500
    assert ver['video_count'] == 2
    assert ver['audio_count'] == 1
    assert isinstance(ver['sample_media_ids'], list)
    assert len(ver['sample_media_ids']) == 3


async def test_group_by_channel_unknown_bucket(test_database):
    await _add('u://nochan', channel=None, media_type=MediaType.VIDEO)

    result = await media_details.get_media_groups(group_by='channel')
    unknown = _find(result['groups'], 'Unknown channel')
    assert unknown is not None
    assert unknown['count'] >= 1


async def test_group_by_released_year_then_month(test_database):
    await _add('u://r1', channel='C', release=datetime(2020, 3, 15))
    await _add('u://r2', channel='C', release=datetime(2025, 7, 1))
    await _add('u://r3', channel='C', release=datetime(2025, 9, 20))
    await _add('u://r4', channel='C', release=datetime(2025, 1, 5))  # inserted last, earliest month

    years = await media_details.get_media_groups(group_by='released', level='year')
    y2025 = _find(years['groups'], '2025')
    y2020 = _find(years['groups'], '2020')
    assert y2025 is not None and y2025['count'] == 3
    assert y2020 is not None and y2020['count'] == 1

    months = await media_details.get_media_groups(group_by='released', level='month', parent='2025')
    # Months sorted chronologically (January -> December), not by insertion or count.
    assert [g['key'] for g in months['groups']] == ['2025-01', '2025-07', '2025-09']
    july = _find(months['groups'], '2025-07')
    assert july['label'] == 'July'
    assert july['count'] == 1


async def test_group_by_downloaded_year(test_database):
    await _add('u://d1', channel='C', downloaded=datetime(2024, 1, 1))
    await _add('u://d2', channel='C', downloaded=datetime(2024, 6, 1))

    years = await media_details.get_media_groups(group_by='downloaded', level='year')
    y2024 = _find(years['groups'], '2024')
    assert y2024 is not None
    assert y2024['count'] == 2


async def test_sample_media_ids_limited_to_4_newest_first(test_database):
    ids = [
        await _add(f'u://big{i}', channel='BigChannel', created=datetime(2026, 1, i + 1))
        for i in range(5)
    ]

    result = await media_details.get_media_groups(group_by='channel')
    big = _find(result['groups'], 'BigChannel')
    assert big['count'] == 5
    assert len(big['sample_media_ids']) == 4
    # newest (latest created_at) first
    assert big['sample_media_ids'][0] == ids[-1]


async def test_group_by_tag_with_untagged_bucket(test_database):
    async with db.get_async_session() as session:
        user = User(username='tagger', password_hash='x')
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = user.id

    a = await _add('u://t_a', channel='C', duration=10)
    b = await _add('u://t_b', channel='C', duration=20)
    c = await _add('u://t_c', channel='C')
    await _add('u://t_d', channel='C')  # untagged

    async with db.get_async_session() as session:
        music = Tag(user_id=uid, name='music')
        talks = Tag(user_id=uid, name='talks')
        session.add(music)
        session.add(talks)
        await session.flush()
        session.add(MediaTag(user_id=uid, media_details_id=a, tag_id=music.id))
        session.add(MediaTag(user_id=uid, media_details_id=b, tag_id=music.id))
        session.add(MediaTag(user_id=uid, media_details_id=c, tag_id=talks.id))
        music_id = music.id
        await session.commit()

    result = await media_details.get_media_groups(group_by='tag', rating_user_id=uid)
    groups = result['groups']

    music_group = _find(groups, str(music_id))
    assert music_group is not None
    assert music_group['label'] == 'music'
    assert music_group['count'] == 2
    assert music_group['total_duration'] == 30

    untagged = _find(groups, 'untagged')
    assert untagged is not None
    assert untagged['label'] == 'Untagged'
    assert untagged['count'] >= 1  # at least media d (+ base fixture media)


# --- Leaf navigation filters on get_all_media_details ---


async def test_list_filter_by_channel(test_database):
    await _add('u://cx1', channel='ChanX')
    await _add('u://cx2', channel='ChanX')
    await _add('u://cy1', channel='ChanY')

    res = await media_details.get_all_media_details(channel='ChanX')
    assert res['count_records'] == 2
    assert all(r['channel'] == 'ChanX' for r in res['records'])


async def test_list_filter_channel_unknown_bucket(test_database):
    await _add('u://nochan2', channel=None)

    res = await media_details.get_all_media_details(channel='Unknown channel')
    assert res['count_records'] >= 1
    assert all(r['channel'] is None for r in res['records'])


async def test_list_filter_untagged(test_database):
    async with db.get_async_session() as session:
        user = User(username='leaf_tagger', password_hash='x')
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = user.id

    tagged = await _add('u://tg1', channel='C')
    await _add('u://utg1', channel='C')
    async with db.get_async_session() as session:
        tag = Tag(user_id=uid, name='keep')
        session.add(tag)
        await session.flush()
        session.add(MediaTag(user_id=uid, media_details_id=tagged, tag_id=tag.id))
        await session.commit()

    res = await media_details.get_all_media_details(untagged=True, rating_user_id=uid)
    urls = {r['url'] for r in res['records']}
    assert 'u://tg1' not in urls
    assert 'u://utg1' in urls


async def test_list_filter_date_range_released_month(test_database):
    await _add('u://dr1', channel='C', release=datetime(2025, 7, 10))
    await _add('u://dr2', channel='C', release=datetime(2025, 9, 10))
    await _add('u://dr3', channel='C', release=datetime(2024, 7, 10))

    res = await media_details.get_all_media_details(
        date_field='released', date_year=2025, date_month=7
    )
    assert {r['url'] for r in res['records']} == {'u://dr1'}


async def test_list_filter_date_range_year_only(test_database):
    await _add('u://y1', channel='C', downloaded=datetime(2023, 2, 1))
    await _add('u://y2', channel='C', downloaded=datetime(2023, 11, 1))
    await _add('u://y3', channel='C', downloaded=datetime(2022, 5, 1))

    res = await media_details.get_all_media_details(date_field='downloaded', date_year=2023)
    assert {r['url'] for r in res['records']} == {'u://y1', 'u://y2'}
