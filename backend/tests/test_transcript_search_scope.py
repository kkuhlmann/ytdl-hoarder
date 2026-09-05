"""Transcript search is scoped to the media the library filter currently selects.

Every case here goes through real SQL against a real pgvector index, because the whole
class of bug this guards is invisible to a mock: a filtered vector search that returns
too few rows returns them successfully.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import text

from database import db
from models import (
    MediaAccess,
    MediaDetails,
    MediaType,
    SourceType,
    TaskStatus,
    TranscriptBlock,
    User,
)
from services import transcript as transcript_service

EMBEDDING_DIM = 384


@pytest.fixture(autouse=True)
def _clear_search_cache():
    transcript_service.semantic_cache.clear()
    yield
    transcript_service.semantic_cache.clear()


class _StubEmbedder:
    """Stands in for OnnxEmbedder so no ONNX session is loaded for a SQL test."""

    def encode(self, sentences, normalize_embeddings=True):
        return np.full((len(sentences), EMBEDDING_DIM), 0.05, dtype=np.float32)


def _vector(value: float) -> str:
    return '[' + ','.join([str(value)] * EMBEDDING_DIM) + ']'


def _seed_user(session, username: str) -> int:
    user = User(username=username, password_hash='x', is_approved=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


def _seed_media(
    session,
    *,
    owner_id: int,
    url: str,
    channel: str,
    title: str,
    released: datetime,
    blocks: list[str],
    status: str = TaskStatus.COMPLETE.value,
    grant_access_to: int | None = None,
    embedding_value: float = 0.05,
) -> int:
    media = MediaDetails(
        url=url,
        media_type=MediaType.VIDEO,
        channel=channel,
        title=title,
        status=status,
        release_timestamp=released,
        downloaded_at=released,
        owner_id=owner_id,
    )
    session.add(media)
    session.commit()
    session.refresh(media)

    for index, body in enumerate(blocks):
        block = TranscriptBlock(
            start_time=float(index * 10),
            end_time=float(index * 10 + 10),
            text=body,
            media_details_id=media.id,
        )
        session.add(block)
    session.commit()

    block_ids = [
        row[0]
        for row in session.execute(
            text('SELECT id FROM transcript_blocks WHERE media_details_id = :m ORDER BY id'),
            {'m': media.id},
        )
    ]
    for block_id in block_ids:
        session.execute(
            text(
                'INSERT INTO transcript_embeddings (transcript_block_id, embedding) '
                'VALUES (:b, CAST(:e AS vector))'
            ),
            {'b': block_id, 'e': _vector(embedding_value)},
        )

    if grant_access_to is not None:
        session.add(
            MediaAccess(
                user_id=grant_access_to,
                media_details_id=media.id,
                source_type=SourceType.DIRECT,
                source_id=0,
            )
        )
    session.commit()
    return media.id


@pytest.fixture
def library(clean_database, pgvector_schema):
    """Two channels in two different years, plus an unrelated second user."""
    session = db.get_sync_session()
    try:
        owner_id = _seed_user(session, 'owner')
        stranger_id = _seed_user(session, 'stranger')

        nasa_id = _seed_media(
            session,
            owner_id=owner_id,
            url='https://example.com/nasa',
            channel='NASA',
            title='Lunar Lander Update',
            released=datetime(2024, 3, 4, tzinfo=UTC),
            blocks=['the spacecraft lander touches down', 'spacecraft orbital insertion burn'],
            grant_access_to=owner_id,
        )
        esa_id = _seed_media(
            session,
            owner_id=owner_id,
            url='https://example.com/esa',
            channel='ESA',
            title='Ariane Launch Recap',
            released=datetime(2025, 7, 9, tzinfo=UTC),
            blocks=['the spacecraft launch window opens', 'spacecraft stage separation'],
            grant_access_to=owner_id,
        )
        return SimpleNamespace(
            owner_id=owner_id, stranger_id=stranger_id, nasa_id=nasa_id, esa_id=esa_id
        )
    finally:
        session.close()


async def _search(**kwargs):
    return await transcript_service.get_hybrid_search_results(
        _StubEmbedder(), 'spacecraft', **kwargs
    )


def _media_ids(hits) -> set[int]:
    return {hit['media_details']['id'] for hit in hits}


WEIGHTS = [1.0, 0.0, 0.5]


@pytest.mark.parametrize('weight', WEIGHTS)
async def test_unscoped_search_spans_the_library(library, weight):
    hits = await _search(
        semantic_weight=weight, user_id=library.owner_id, rating_user_id=library.owner_id
    )

    assert _media_ids(hits) == {library.nasa_id, library.esa_id}


@pytest.mark.parametrize('weight', WEIGHTS)
async def test_channel_scope_excludes_the_other_channel(library, weight):
    hits = await _search(
        semantic_weight=weight,
        user_id=library.owner_id,
        rating_user_id=library.owner_id,
        channel='NASA',
    )

    assert _media_ids(hits) == {library.nasa_id}


@pytest.mark.parametrize('weight', WEIGHTS)
async def test_year_alone_scopes_to_the_whole_year(library, weight):
    hits = await _search(
        semantic_weight=weight,
        user_id=library.owner_id,
        rating_user_id=library.owner_id,
        date_field='released',
        date_year=2024,
    )

    assert _media_ids(hits) == {library.nasa_id}


@pytest.mark.parametrize('weight', WEIGHTS)
async def test_month_narrows_further_than_the_year(library, weight):
    in_month = await _search(
        semantic_weight=weight,
        user_id=library.owner_id,
        rating_user_id=library.owner_id,
        date_field='released',
        date_year=2024,
        date_month=3,
    )
    other_month = await _search(
        semantic_weight=weight,
        user_id=library.owner_id,
        rating_user_id=library.owner_id,
        date_field='released',
        date_year=2024,
        date_month=4,
    )

    assert _media_ids(in_month) == {library.nasa_id}
    assert other_month == []


@pytest.mark.parametrize('weight', WEIGHTS)
async def test_standard_search_honours_the_boolean_operators(library, weight):
    both = await _search(
        semantic_weight=weight,
        user_id=library.owner_id,
        rating_user_id=library.owner_id,
        standard_search='NASA || Ariane',
    )
    neither = await _search(
        semantic_weight=weight,
        user_id=library.owner_id,
        rating_user_id=library.owner_id,
        standard_search='NASA && Ariane',
    )

    assert _media_ids(both) == {library.nasa_id, library.esa_id}
    assert neither == []


@pytest.mark.parametrize('weight', WEIGHTS)
async def test_a_user_with_no_access_and_no_ownership_sees_nothing(library, weight):
    hits = await _search(
        semantic_weight=weight,
        user_id=library.stranger_id,
        rating_user_id=library.stranger_id,
    )

    assert hits == []


@pytest.mark.parametrize('weight', WEIGHTS)
async def test_owner_can_search_kept_transcripts_of_their_deleted_media(
    clean_database, pgvector_schema, weight
):
    """A soft delete drops every media_access row, the owner's included.

    Without the owner branch in the scope the transcripts survive on disk and in the
    index but become unreachable to the only person entitled to them.
    """
    session = db.get_sync_session()
    try:
        owner_id = _seed_user(session, 'owner')
        stranger_id = _seed_user(session, 'stranger')
        deleted_id = _seed_media(
            session,
            owner_id=owner_id,
            url='https://example.com/gone',
            channel='NASA',
            title='Artemis Recap',
            released=datetime(2024, 3, 4, tzinfo=UTC),
            blocks=['the spacecraft crew module separated cleanly'],
            status=TaskStatus.DELETED.value,
            grant_access_to=None,
        )
    finally:
        session.close()

    as_owner = await _search(semantic_weight=weight, user_id=owner_id, rating_user_id=owner_id)
    as_stranger = await _search(
        semantic_weight=weight, user_id=stranger_id, rating_user_id=stranger_id
    )

    assert _media_ids(as_owner) == {deleted_id}
    assert as_stranger == []


@pytest.mark.parametrize('weight', WEIGHTS)
async def test_a_narrow_scope_still_returns_every_matching_block(
    clean_database, pgvector_schema, weight
):
    """A scope surrounded by nearer non-matching vectors still yields all of its blocks.

    The needle sits further from the query vector than all 60 haystack media, so any
    plan that ranks first and filters afterwards loses it. (At this size the planner
    picks a filtered scan whatever the query shape, so this cannot exercise pgvector's
    HNSW post-filter itself — `test_scoped_vector_cte_is_materialized` pins that.)
    """
    session = db.get_sync_session()
    try:
        owner_id = _seed_user(session, 'owner')
        # The haystack sits nearer the query vector than the needle, so a post-filtered
        # scan would fill its candidate list before ever reaching the needle.
        for index in range(60):
            _seed_media(
                session,
                owner_id=owner_id,
                url=f'https://example.com/noise-{index}',
                channel='Noise',
                title=f'Noise {index}',
                released=datetime(2025, 1, 1, tzinfo=UTC),
                blocks=['unrelated spacecraft chatter about the weather'],
                grant_access_to=owner_id,
                embedding_value=0.05,
            )
        needle_id = _seed_media(
            session,
            owner_id=owner_id,
            url='https://example.com/needle',
            channel='Needle',
            title='Needle',
            released=datetime(2024, 6, 1, tzinfo=UTC),
            blocks=[f'the spacecraft lander touches down again {n}' for n in range(12)],
            grant_access_to=owner_id,
            embedding_value=-0.05,
        )
    finally:
        session.close()

    hits = await _search(
        semantic_weight=weight,
        user_id=owner_id,
        rating_user_id=owner_id,
        channel='Needle',
    )

    assert _media_ids(hits) == {needle_id}
    if weight == 1.0:
        assert len(hits) == 12


async def test_scope_is_part_of_the_cache_key(library):
    unscoped = await _search(
        semantic_weight=1.0, user_id=library.owner_id, rating_user_id=library.owner_id
    )
    scoped = await _search(
        semantic_weight=1.0,
        user_id=library.owner_id,
        rating_user_id=library.owner_id,
        channel='NASA',
    )

    assert _media_ids(unscoped) == {library.nasa_id, library.esa_id}
    assert _media_ids(scoped) == {library.nasa_id}
