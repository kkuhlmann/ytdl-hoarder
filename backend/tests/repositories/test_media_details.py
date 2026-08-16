from datetime import datetime

from models import MediaDetails, MediaType, TaskStatus
from repositories import media_details


async def test_get_media_details_by_url_and_media_type(test_database):
    md = await media_details.get_media_details_by_url_and_media_type(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        MediaType.AUDIO.value,
    )
    assert md is not None
    assert md.id == 1
    assert md.url == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


async def test_get_media_details_by_id(test_database):
    md = await media_details.get_media_details_by_id(1)
    assert md is not None
    assert md.id == 1


async def test_upsert_media_details_inserts_new(test_database):
    md = await media_details.upsert_media_details(
        MediaDetails(
            url='https://www.youtube.com/watch?v=AC3Ejf7vPEY',
            media_type=MediaType.AUDIO,
            channel='Colorize',
            title='VisionV - Blossom',
            playlist_index=None,
            status=TaskStatus.NONE,
        )
    )
    assert md is not None
    assert md.id is not None
    assert md.channel == 'Colorize'


async def test_get_all_media_details(test_database):
    result = await media_details.get_all_media_details()
    assert result['count_records'] >= 2
    assert len(result['records']) >= 2


async def test_get_all_media_details_with_search(test_database):
    result = await media_details.get_all_media_details(search='Rick Astley')
    assert result['count_records'] >= 1
    # Search matches channel OR title - check that at least one record has 'Rick Astley' somewhere
    record = result['records'][0]
    assert 'Rick Astley' in record['channel'] or 'Rick Astley' in record['title']


# --- Boolean search operators (&& / ||) ---
# Seeded rows (see conftest test_media_details):
#   id 1: channel='Rick Astley', title='... (Official Music Video)'
#   id 2: channel='MusRest',     title='... (Remastered 4K 60fps,AI)'


async def test_search_single_term_unchanged(test_database):
    # A plain term (no operators) matches channel OR title as a substring.
    result = await media_details.get_all_media_details(search='MusRest')
    assert result['count_records'] == 1
    assert result['records'][0]['channel'] == 'MusRest'


async def test_search_and_operator(test_database):
    # '&&' requires every term to be present (each in channel or title).
    result = await media_details.get_all_media_details(search='MusRest && Remastered')
    assert result['count_records'] == 1
    assert result['records'][0]['channel'] == 'MusRest'

    # Terms may land in different fields of the same row: row 2 has 'MusRest'
    # as its channel and 'Rick Astley' in its title, so it satisfies both.
    cross_field = await media_details.get_all_media_details(search='Rick Astley && MusRest')
    assert cross_field['count_records'] == 1
    assert cross_field['records'][0]['channel'] == 'MusRest'

    # No single row contains both 'Official' (row 1 only) and 'MusRest' (row 2 only).
    none_result = await media_details.get_all_media_details(search='Official && MusRest')
    assert none_result['count_records'] == 0


async def test_search_or_operator(test_database):
    # '||' matches rows containing either term (row 2 via 'MusRest', row 1 via 'Official').
    result = await media_details.get_all_media_details(search='MusRest || Official')
    assert result['count_records'] == 2


async def test_search_mixed_precedence(test_database):
    # '&&' binds tighter than '||': (MusRest AND Official) OR Remastered.
    # The AND group matches neither row; only row 2 matches via the trailing OR term.
    # A count of 1 distinguishes correct precedence from flat-AND (0) and flat-OR (2).
    result = await media_details.get_all_media_details(search='MusRest && Official || Remastered')
    assert result['count_records'] == 1
    assert result['records'][0]['channel'] == 'MusRest'


async def test_search_single_ampersand_is_literal(test_database):
    # A single '&' is NOT an operator; it stays part of the literal term.
    await media_details.upsert_media_details(
        MediaDetails(
            url='https://www.youtube.com/watch?v=literalAmp01',
            media_type=MediaType.AUDIO,
            channel='Cooks',
            title='Salt & Pepper Diner',
            playlist_index=None,
            status=TaskStatus.COMPLETE,
        )
    )
    result = await media_details.get_all_media_details(search='Salt & Pepper')
    assert result['count_records'] == 1
    assert result['records'][0]['title'] == 'Salt & Pepper Diner'


async def test_search_operator_only_is_noop(test_database):
    # Operator-only / whitespace searches add no filter (same as an empty search).
    baseline = await media_details.get_all_media_details()
    for noop in ('&&', '||', '   '):
        result = await media_details.get_all_media_details(search=noop)
        assert result['count_records'] == baseline['count_records']


async def test_update_media_details(test_database):
    # update_one now returns the updated record directly (no extra fetch needed)
    updated = await media_details.update_one(1, {'title': 'Updated Title'})
    assert updated is not None
    assert updated.id == 1
    assert updated.title == 'Updated Title'


async def test_upsert_media_details(test_database):
    # Test inserting new record
    new_md = MediaDetails(
        url='https://www.youtube.com/watch?v=wbL2lMn34Yw',
        media_type=MediaType.VIDEO,
        channel='New Channel',
        title='New Video',
        status=TaskStatus.NONE,
    )
    result = await media_details.upsert_media_details(new_md)
    assert result is not None
    assert result.id is not None
    original_id = result.id

    # Test updating existing record (same url + media_type)
    updated_md = MediaDetails(
        url='https://www.youtube.com/watch?v=wbL2lMn34Yw',
        media_type=MediaType.VIDEO,
        channel='New Channel',
        title='Updated Video Title',
        status=TaskStatus.COMPLETE,
    )
    result = await media_details.upsert_media_details(updated_md)
    assert result.id == original_id
    assert result.title == 'Updated Video Title'
    assert result.status == TaskStatus.COMPLETE


async def test_get_all_media_details_with_sorting(test_database):
    # Add records with different release timestamps
    await media_details.upsert_media_details(
        MediaDetails(
            url='https://youtube.com/watch?v=_b5V1wchZJU',
            media_type=MediaType.VIDEO,
            title='Oldest',
            release_timestamp=datetime(2020, 1, 1),
            status=TaskStatus.COMPLETE,
        )
    )
    await media_details.upsert_media_details(
        MediaDetails(
            url='https://youtube.com/watch?v=GJa0Bv5DXBc',
            media_type=MediaType.VIDEO,
            title='Newest',
            release_timestamp=datetime(2025, 1, 1),
            status=TaskStatus.COMPLETE,
        )
    )
    await media_details.upsert_media_details(
        MediaDetails(
            url='https://youtube.com/watch?v=dJRsWJqDjFE',
            media_type=MediaType.VIDEO,
            title='Middle',
            release_timestamp=datetime(2023, 6, 15),
            status=TaskStatus.COMPLETE,
        )
    )

    # Test descending sort
    result_desc = await media_details.get_all_media_details(
        status='COMPLETE', sort_by='release_timestamp', sort_direction='desc'
    )
    titles_desc = [
        r['title'] for r in result_desc['records'] if r['title'] in ['Oldest', 'Newest', 'Middle']
    ]
    assert titles_desc == ['Newest', 'Middle', 'Oldest'], f'Expected desc order, got {titles_desc}'

    # Test ascending sort
    result_asc = await media_details.get_all_media_details(
        status='COMPLETE', sort_by='release_timestamp', sort_direction='asc'
    )
    titles_asc = [
        r['title'] for r in result_asc['records'] if r['title'] in ['Oldest', 'Newest', 'Middle']
    ]
    assert titles_asc == ['Oldest', 'Middle', 'Newest'], f'Expected asc order, got {titles_asc}'
