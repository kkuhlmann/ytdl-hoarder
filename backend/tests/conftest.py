from datetime import UTC, datetime

import bcrypt
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel
from testcontainers.community.postgres import PostgresContainer

import rate_limit
from database import db
from models import (
    Clip,
    DownloadJob,
    JobType,
    MediaAccess,
    MediaDetails,
    MediaType,
    Subscription,
    TaskRecord,
    TaskStatus,
    TaskType,
    TranscriptBlock,
)

# Test data
test_subscriptions = [
    Subscription(
        id=1,
        url='https://www.youtube.com/@RickAstleyYT',
        channel='Lesh',
        audio_only=True,
        media_type=MediaType.AUDIO,
        string_match='Progressive House',
        overwrite=False,
        date_filter=datetime(2023, 7, 27),
        job_type=JobType.CHANNEL_SUBSCRIPTION,
        generate_transcript=False,
    ),
    Subscription(
        id=2,
        url='https://www.youtube.com/watch?v=AC3Ejf7vPEY&list=PLJ8cMiYb3G5fEBBRGG3cXJJTPSBJb2MLa',
        channel='Weezer (Blue) Full Album - Weezer [Audio]',
        audio_only=True,
        media_type=MediaType.AUDIO,
        string_match=None,
        overwrite=False,
        date_filter=None,
        job_type=JobType.PLAYLIST_SUBSCRIPTION,
        generate_transcript=False,
    ),
]

test_media_details = [
    MediaDetails(
        id=1,
        url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        media_type=MediaType.AUDIO,
        channel='Rick Astley',
        title='Rick Astley - Never Gonna Give You Up (Official Music Video)',
        playlist_index=None,
        status=TaskStatus.COMPLETE,
    ),
    MediaDetails(
        id=2,
        url='https://www.youtube.com/watch?v=lYBUbBu4W08',
        media_type=MediaType.AUDIO,
        channel='MusRest',
        title='Rick Astley - Never Gonna Give You Up (Remastered 4K 60fps,AI)',
        playlist_index=None,
        status=TaskStatus.COMPLETE,
    ),
]

test_download_jobs = [
    DownloadJob(
        id=1,
        url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        audio_only=True,
        download_playlist=False,
        overwrite=False,
        media_type=MediaType.AUDIO,
        title=None,
        job_type=JobType.NORMAL_DOWNLOAD,
        subscription_id=None,
        media_details_id=1,
    ),
    DownloadJob(
        id=2,
        url='https://www.youtube.com/watch?v=lYBUbBu4W08',
        audio_only=True,
        download_playlist=False,
        overwrite=False,
        media_type=MediaType.AUDIO,
        title=None,
        job_type=JobType.NORMAL_DOWNLOAD,
        subscription_id=None,
        media_details_id=2,
    ),
]

test_task_records = [
    # COMPLETE download task
    TaskRecord(
        id=1,
        task_id='task-download-complete-1',
        task_type=TaskType.DOWNLOAD,
        status=TaskStatus.COMPLETE,
        percent_complete=100,
        title='Rick Astley - Never Gonna Give You Up',
        channel='Rick Astley',
        media_type=MediaType.AUDIO,
        download_job_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    ),
    # FAILED download task
    TaskRecord(
        id=2,
        task_id='task-download-failed-2',
        task_type=TaskType.DOWNLOAD,
        status=TaskStatus.FAILED,
        percent_complete=50,
        status_message='Download failed: network error',
        title='Failed Download',
        channel='Test Channel',
        media_type=MediaType.AUDIO,
        download_job_url='https://www.youtube.com/watch?v=_b5V1wchZJU',
    ),
    # COMPLETE transcript task (depends on download)
    TaskRecord(
        id=3,
        task_id='task-transcript-complete-3',
        task_type=TaskType.TRANSCRIPT_GENERATION,
        status=TaskStatus.COMPLETE,
        percent_complete=100,
        upstream_task_ids=['task-download-complete-1'],
        title='Rick Astley - Never Gonna Give You Up',
        channel='Rick Astley',
        media_type=MediaType.AUDIO,
    ),
    # UPSTREAM_FAILED transcript task
    TaskRecord(
        id=4,
        task_id='task-transcript-upstream-4',
        task_type=TaskType.TRANSCRIPT_GENERATION,
        status=TaskStatus.UPSTREAM_FAILED,
        percent_complete=0,
        upstream_task_ids=['task-download-failed-2'],
        title='Failed Download',
        channel='Test Channel',
        media_type=MediaType.AUDIO,
    ),
    # QUEUED task
    TaskRecord(
        id=5,
        task_id='task-download-queued-5',
        task_type=TaskType.DOWNLOAD,
        status=TaskStatus.QUEUED,
        percent_complete=0,
        title='Queued Download',
        channel='Queue Channel',
        media_type=MediaType.VIDEO,
        download_job_url='https://www.youtube.com/watch?v=GJa0Bv5DXBc',
        queue_sequence=1,
    ),
    # IN_PROGRESS task
    TaskRecord(
        id=6,
        task_id='task-download-progress-6',
        task_type=TaskType.DOWNLOAD,
        status=TaskStatus.IN_PROGRESS,
        percent_complete=25,
        title='In Progress Download',
        channel='Progress Channel',
        media_type=MediaType.VIDEO,
        download_job_url='https://www.youtube.com/watch?v=dJRsWJqDjFE',
        queue_sequence=2,
    ),
]

test_transcript_blocks = [
    # Two blocks for media_details[0] (id=1)
    TranscriptBlock(
        id=1,
        media_details_id=1,
        start_time=0.0,
        end_time=5.0,
        text='Never gonna give you up, never gonna let you down.',
        transcript_model='tiny.en',
        embedding_model='all-MiniLM-L6-v2',
    ),
    TranscriptBlock(
        id=2,
        media_details_id=1,
        start_time=5.0,
        end_time=10.0,
        text='Never gonna run around and desert you.',
        transcript_model='tiny.en',
        embedding_model='all-MiniLM-L6-v2',
    ),
    # One block for media_details[1] (id=2)
    TranscriptBlock(
        id=3,
        media_details_id=2,
        start_time=0.0,
        end_time=5.0,
        text='This is the remastered version.',
        transcript_model='tiny.en',
        embedding_model='all-MiniLM-L6-v2',
    ),
]


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Give every test a fresh rate-limit budget.

    The limiters are module-level singletons keyed on client address, and the whole
    suite shares one TestClient address, so without this the budget is consumed
    across unrelated tests and whichever test happens to run 31st fails.
    """
    for limiter in rate_limit.ALL_LIMITERS:
        limiter.reset()


@pytest.fixture(scope='session', autouse=True)
def _fast_bcrypt():
    """Hash at bcrypt's minimum cost instead of the production cost 12 (~250ms a hash).

    `checkpw` reads the cost out of the hash string, so register-then-login tests still
    exercise the real hash/verify path — patching `hash_password` instead would bypass
    the very code TestPasswordHashing covers.
    """
    real_gensalt = bcrypt.gensalt
    mp = pytest.MonkeyPatch()  # the monkeypatch fixture is function-scoped
    mp.setattr(bcrypt, 'gensalt', lambda rounds=12, prefix=b'2b': real_gensalt(4, prefix))
    yield
    mp.undo()


@pytest.fixture(scope='session')
def postgres_container():
    """One throwaway PostgreSQL for the whole session.

    Durability is turned off because the per-test TRUNCATE is the suite's single
    biggest cost and it is almost entirely fsync of the new relfilenodes it creates
    (measured: 136ms of the 160ms `test_database` setup). Nothing here has to survive
    a crash — the container is discarded at the end of the run.
    """
    postgres = PostgresContainer('pgvector/pgvector:pg17').with_command(
        'postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off'
    )
    with postgres:
        yield postgres


def _setup_database_engines(postgres_container):
    """Create database engines from the postgres container.

    Returns tuple of (async_url, sync_url, async_engine, sync_engine,
                      async_session_factory, sync_session_factory)
    """
    # Get connection URL from container
    base_url = postgres_container.get_connection_url()

    # Convert to async (asyncpg) and sync (psycopg) URLs
    if '+psycopg2' in base_url:
        async_url = base_url.replace('+psycopg2', '+asyncpg')
        sync_url = base_url.replace('+psycopg2', '+psycopg')
    else:
        async_url = base_url.replace('postgresql://', 'postgresql+asyncpg://')
        sync_url = base_url.replace('postgresql://', 'postgresql+psycopg://')

    # Create sync engine (for table creation and sync tests)
    sync_engine = create_engine(
        sync_url,
        echo=False,
        pool_pre_ping=True,
    )

    # Create async engine (for async tests)
    # Use NullPool to avoid event loop issues when TestClient creates its own loop
    # NullPool creates a new connection for each request, avoiding cross-loop issues
    async_engine = create_async_engine(
        async_url,
        echo=False,
        poolclass=NullPool,
    )

    # Create session factories
    async_session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    sync_session_factory = sessionmaker(
        bind=sync_engine,
        expire_on_commit=False,
    )

    return (
        async_url,
        sync_url,
        async_engine,
        sync_engine,
        async_session_factory,
        sync_session_factory,
    )


@pytest.fixture(scope='session')
def _db_engines(postgres_container):
    """Build the engines and the schema once, and point `db` at them for the whole run.

    Nothing restores the `db._*` globals afterwards, and nothing needs to: every client
    site uses a bare `TestClient(app)`, so the lifespan that would call
    `initialize_database()` never runs. A test that does need the lifespan has to
    save and restore these itself.
    """
    (_a, _s, async_engine, sync_engine, async_session_factory, sync_session_factory) = (
        _setup_database_engines(postgres_container)
    )
    SQLModel.metadata.create_all(sync_engine)

    db._async_engine = async_engine
    db._sync_engine = sync_engine
    db._async_session_factory = async_session_factory
    db._sync_session_factory = sync_session_factory

    yield sync_engine

    sync_engine.dispose()
    # The async engine is deliberately not disposed: NullPool holds no connections,
    # and disposal would need an event loop this sync teardown doesn't have.


@pytest.fixture(scope='session')
def pgvector_schema(_db_engines):
    """Create the vector/FTS objects `SQLModel.metadata.create_all` cannot see.

    `transcript_embeddings` and `transcript_blocks.text_search` exist only in
    `baseline_schema.py`'s hand-written block, so without this no transcript-search
    query can run at all here. Request it explicitly; most tests do not need it.

    No teardown: `transcript_embeddings` cascades off `transcript_blocks`, which
    `_reset_sql` already empties before every test.
    """
    with _db_engines.begin() as conn:
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
        conn.execute(
            text(
                'ALTER TABLE transcript_blocks '
                'ADD COLUMN IF NOT EXISTS text_search tsvector '
                "GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED"
            )
        )
        conn.execute(
            text(
                'CREATE INDEX IF NOT EXISTS idx_transcript_blocks_fts '
                'ON transcript_blocks USING GIN(text_search)'
            )
        )
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS transcript_embeddings (
                    transcript_block_id INTEGER PRIMARY KEY
                        REFERENCES transcript_blocks(id) ON DELETE CASCADE,
                    embedding vector(384)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS ix_transcript_embeddings_embedding
                ON transcript_embeddings
                USING hnsw (embedding vector_cosine_ops)
            """)
        )
    return _db_engines


@pytest.fixture(scope='session')
def _reset_sql(_db_engines):
    """One round-trip that empties every table and rewinds every sequence.

    DELETE rather than TRUNCATE: on tables this small the MVCC delete is far cheaper
    than TRUNCATE's relfilenode churn (measured 8.9ms against 51.9ms per test, and
    this runs before every DB-backed test). Sequences are rewound explicitly —
    RESTART IDENTITY would have covered the serial columns but never standalone
    task_queue_sequence, and several tests depend on fresh-database id assignment.
    """
    with _db_engines.begin() as conn:
        sequences = [
            row[0]
            for row in conn.execute(
                text("SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'")
            )
        ]
    # Children first: DELETE has no CASCADE, and sorted_tables is parents-first.
    statements = [
        f'DELETE FROM "{t.name}"'  # noqa: S608 — names come from our own metadata
        for t in reversed(SQLModel.metadata.sorted_tables)
    ]
    statements += [f'ALTER SEQUENCE "{name}" RESTART' for name in sequences]
    return '; '.join(statements)


def _reset_database(sync_engine, reset_sql):
    with sync_engine.begin() as conn:
        # A leaked in-transaction session would hold row locks these DELETEs need;
        # fail loudly instead of hanging the suite.
        conn.exec_driver_sql("SET lock_timeout = '5s'")
        conn.exec_driver_sql(reset_sql)


def _populate_test_data(sync_session_factory):
    """Insert test data using sync session.

    Note: user_id fields are left NULL here. The authenticated_client fixture
    backfills them after creating the test user, so that FK constraints are satisfied.
    """
    # Use naive datetime for created_at to match PostgreSQL TIMESTAMP (without timezone)
    now = datetime.now(UTC).replace(tzinfo=None)

    with sync_session_factory() as session:
        # Insert subscriptions first (no FK dependencies)
        for sub in test_subscriptions:
            new_sub = Subscription(
                url=sub.url,
                channel=sub.channel,
                audio_only=sub.audio_only,
                media_type=sub.media_type,
                string_match=sub.string_match,
                overwrite=sub.overwrite,
                date_filter=sub.date_filter,
                job_type=sub.job_type,
                generate_transcript=sub.generate_transcript,
                created_at=now,
            )
            session.add(new_sub)

        # Insert task_records (before media_details since MD has FK to TaskRecord)
        for tr in test_task_records:
            new_tr = TaskRecord(
                task_id=tr.task_id,
                upstream_task_ids=tr.upstream_task_ids,
                task_type=tr.task_type,
                percent_complete=tr.percent_complete,
                eta_seconds=tr.eta_seconds,
                status=tr.status,
                status_message=tr.status_message,
                title=tr.title,
                channel=tr.channel,
                release_timestamp=tr.release_timestamp,
                media_type=tr.media_type,
                download_job_url=tr.download_job_url,
                queue_sequence=tr.queue_sequence,
                created_at=now,
                updated_at=now,
            )
            session.add(new_tr)

        # flush, not commit: the FKs below need their parents to have ids, which a
        # flush assigns — one commit for the whole seed is measurably cheaper.
        session.flush()

        # Insert media_details (with FK to task_records)
        for i, md in enumerate(test_media_details):
            new_md = MediaDetails(
                url=md.url,
                media_type=md.media_type,
                channel=md.channel,
                title=md.title,
                playlist_index=md.playlist_index,
                status=md.status,
                download_task_record_id=1 if i == 0 else None,
                transcript_task_record_id=3 if i == 0 else None,
                created_at=now,
            )
            session.add(new_md)

        session.flush()

        # Insert download_jobs (after media_details exist)
        for dj in test_download_jobs:
            new_dj = DownloadJob(
                url=dj.url,
                audio_only=dj.audio_only,
                download_playlist=dj.download_playlist,
                overwrite=dj.overwrite,
                media_type=dj.media_type,
                title=dj.title,
                job_type=dj.job_type,
                subscription_id=dj.subscription_id,
                media_details_id=dj.media_details_id,
                created_at=now,
            )
            session.add(new_dj)

        # Insert transcript_blocks (after media_details exist)
        for tb in test_transcript_blocks:
            new_tb = TranscriptBlock(
                media_details_id=tb.media_details_id,
                start_time=tb.start_time,
                end_time=tb.end_time,
                text=tb.text,
                transcript_model=tb.transcript_model,
                embedding_model=tb.embedding_model,
            )
            session.add(new_tb)

        session.commit()


@pytest.fixture(scope='function')
def clean_database(_db_engines, _reset_sql):
    """Empty schema, no seed — for tests that build all their own rows."""
    _reset_database(_db_engines, _reset_sql)
    return _db_engines


@pytest.fixture(scope='function')
def test_database(clean_database):
    """A freshly seeded database for each test.

    Cleaning at setup rather than teardown is deliberate: a previous test that died
    mid-transaction can't then poison this one.
    """
    _populate_test_data(db._sync_session_factory)
    return clean_database


@pytest.fixture(scope='function')
def authenticated_client(test_database):
    """Provide a TestClient that is authenticated as an admin user.

    Creates the first user (auto-admin, auto-approved) and returns a client
    with the auth cookie set. Then backfills test data with the user's ID so
    that user-scoped queries return the test data.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import update

    from main import app

    client = TestClient(app)
    resp = client.post(
        '/auth/register',
        json={'username': 'testadmin', 'password': 'testpass123'},
    )
    assert resp.status_code == 201, f'Failed to register test user: {resp.text}'

    user_id = resp.json()['id']

    # Backfill test data with the registered user's ID so user-scoped
    # queries (subscriptions, tasks, media) return the test data.
    session = db.get_sync_session()
    try:
        session.execute(update(Subscription).values(user_id=user_id))
        session.execute(update(TaskRecord).values(user_id=user_id))
        session.execute(update(MediaDetails).values(owner_id=user_id))
        session.execute(update(DownloadJob).values(user_id=user_id))

        # Create media_access rows for all test media
        from sqlmodel import select

        md_ids = session.execute(select(MediaDetails.id)).scalars().all()
        for md_id in md_ids:
            session.add(MediaAccess(user_id=user_id, media_details_id=md_id))

        # Backfill clips with user_id (ownership tracked via Clip.user_id, not ClipAccess)
        session.execute(update(Clip).values(user_id=user_id))

        session.commit()
    finally:
        session.close()

    return client
