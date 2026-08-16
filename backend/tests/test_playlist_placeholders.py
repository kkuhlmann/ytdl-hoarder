"""Tests for the placeholder rows a playlist submission produces.

Playlist enumeration is the worst-case wait — minutes on a large list — so the
submitted playlist URL gets its own "Enumerating playlist..." row, which yields to one
row per video once expansion finishes.
"""

import uuid

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from database import db
from models import MediaType, TaskRecord, TaskStatus, TaskType
from tasks.scheduling import run_direct_download_pipeline

PLAYLIST_URL = 'https://www.youtube.com/playlist?list=PLexPaNd'
VIDEO_URLS = [
    'https://www.youtube.com/watch?v=ExPaNdEd001',
    'https://www.youtube.com/watch?v=ExPaNdEd002',
]


class FakeOrch:
    def __init__(self):
        self.specs = []

    def submit_from_thread(self, spec):
        self.specs.append(spec)
        return spec.task_id


def _seed_playlist_placeholder() -> str:
    session = db.get_sync_session()
    try:
        record = TaskRecord(
            task_id='playlist-placeholder',
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.RESOLVING,
            status_message='Enumerating playlist...',
            title=PLAYLIST_URL,
            media_type=MediaType.VIDEO,
            download_job_url=PLAYLIST_URL,
        )
        session.add(record)
        session.commit()
    finally:
        session.close()
    return record.task_id


def _seed_placeholder(url: str) -> str:
    session = db.get_sync_session()
    try:
        record = TaskRecord(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.RESOLVING,
            status_message='Fetching video metadata...',
            title=url,
            media_type=MediaType.VIDEO,
            download_job_url=url,
        )
        session.add(record)
        session.commit()
    finally:
        session.close()
    return record.task_id


def _rows_for(url: str) -> list[TaskRecord]:
    session = db.get_sync_session()
    try:
        return list(
            session.execute(select(TaskRecord).where(TaskRecord.download_job_url == url))
            .scalars()
            .all()
        )
    finally:
        session.close()


async def test_expansion_swaps_the_playlist_row_for_per_video_rows(test_database, monkeypatch):
    task_id = _seed_playlist_placeholder()
    submitted = {
        'url': PLAYLIST_URL,
        'media_type': 'VIDEO',
        'download_playlist': True,
        'placeholder_task_id': task_id,
    }
    expanded = [{'url': url, 'media_type': 'VIDEO'} for url in VIDEO_URLS]

    monkeypatch.setattr('tasks.scheduling.expand_playlists_impl', lambda _jobs: expanded)
    monkeypatch.setattr('tasks.media.filter_completed_downloads_impl', lambda jobs: jobs)
    fake = FakeOrch()
    monkeypatch.setattr('orchestrator.orch', fake)

    result = run_direct_download_pipeline(None, [submitted])

    assert result == {'jobs_started': 2}
    for url in VIDEO_URLS:
        rows = _rows_for(url)
        assert len(rows) == 1
        assert rows[0].status == TaskStatus.RESOLVING
        assert rows[0].pending_payload['url'] == url
        # Must be in the *stored* payload, or startup recovery resumes a populate that
        # can't adopt this row and collides with it instead.
        assert rows[0].pending_payload['placeholder_task_id'] == rows[0].task_id

    playlist_row = _rows_for(PLAYLIST_URL)[0]
    assert playlist_row.status == TaskStatus.SKIPPED
    assert playlist_row.status_message == 'Expanded into 2 video task(s)'
    # Hidden rather than left in the table: the playlist URL is never a download itself.
    assert playlist_row.deleted_at is not None

    # Each populate job carries the id of the row it must adopt
    dispatched = {spec.args[0]['url']: spec.args[0]['placeholder_task_id'] for spec in fake.specs}
    assert set(dispatched) == set(VIDEO_URLS)
    assert all(placeholder for placeholder in dispatched.values())


async def test_single_url_submission_keeps_the_routers_placeholder(test_database, monkeypatch):
    url = 'https://www.youtube.com/watch?v=ExPaNdEd003'
    submitted = {'url': url, 'media_type': 'VIDEO', 'placeholder_task_id': 'router-placeholder'}

    monkeypatch.setattr('tasks.scheduling.expand_playlists_impl', lambda jobs: jobs)
    monkeypatch.setattr('tasks.media.filter_completed_downloads_impl', lambda jobs: jobs)
    fake = FakeOrch()
    monkeypatch.setattr('orchestrator.orch', fake)

    run_direct_download_pipeline(None, [submitted])

    assert fake.specs[0].args[0]['placeholder_task_id'] == 'router-placeholder'
    assert _rows_for(url) == []


async def test_playlist_that_expands_to_nothing_still_retires_its_row(test_database, monkeypatch):
    """Otherwise the row sits in RESOLVING holding the playlist URL's active-unique slot."""
    task_id = _seed_playlist_placeholder()
    submitted = {
        'url': PLAYLIST_URL,
        'media_type': 'VIDEO',
        'download_playlist': True,
        'placeholder_task_id': task_id,
    }

    monkeypatch.setattr('tasks.scheduling.expand_playlists_impl', lambda _jobs: [])
    monkeypatch.setattr('orchestrator.orch', FakeOrch())

    assert run_direct_download_pipeline(None, [submitted]) == {'jobs_started': 0}

    playlist_row = _rows_for(PLAYLIST_URL)[0]
    assert playlist_row.status == TaskStatus.SKIPPED
    assert playlist_row.status_message == 'Expanded into 0 video task(s)'


async def test_registered_pipeline_leaves_a_handed_off_placeholder_alone(
    test_database, monkeypatch
):
    """Ownership of the placeholder transfers to the populate job at submit.

    Exercised through the *registered* callable, not the bare body: the pipeline holds
    its lane slot until it returns, so anything that retires the row on the way out
    always beats the populate job to it, and the chain then stands down instead of
    downloading. Every direct single-URL submission goes through this path.
    """
    from orchestrator import DIRECT_DOWNLOAD_PIPELINE_JOB
    from orchestrator.jobs import get_job_definition
    from tasks.registry import register_all_jobs

    url = 'https://www.youtube.com/watch?v=ExPaNdEd004'
    task_id = 'handed-off-placeholder'
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.RESOLVING,
                status_message='Fetching video metadata...',
                title=url,
                media_type=MediaType.VIDEO,
                download_job_url=url,
            )
        )
        session.commit()
    finally:
        session.close()

    submitted = {'url': url, 'media_type': 'VIDEO', 'placeholder_task_id': task_id}
    monkeypatch.setattr('tasks.scheduling.expand_playlists_impl', lambda jobs: jobs)
    monkeypatch.setattr('tasks.media.filter_completed_downloads_impl', lambda jobs: jobs)
    monkeypatch.setattr('orchestrator.orch', FakeOrch())

    register_all_jobs()
    get_job_definition(DIRECT_DOWNLOAD_PIPELINE_JOB).fn(None, [submitted])

    row = _rows_for(url)[0]
    assert row.status == TaskStatus.RESOLVING, 'the queued populate job still has to adopt this row'


async def test_pipeline_retires_a_placeholder_it_never_handed_off(test_database, monkeypatch):
    """A raise before fan-out must still clear the row, or the submission hangs in RESOLVING."""
    url = 'https://www.youtube.com/watch?v=ExPaNdEd005'
    task_id = _seed_placeholder(url)
    submitted = {'url': url, 'media_type': 'VIDEO', 'placeholder_task_id': task_id}

    def boom(_jobs):
        msg = 'yt-dlp enumeration blew up'
        raise RuntimeError(msg)

    monkeypatch.setattr('tasks.scheduling.expand_playlists_impl', boom)
    monkeypatch.setattr('orchestrator.orch', FakeOrch())

    with pytest.raises(RuntimeError):
        run_direct_download_pipeline(None, [submitted])

    row = _rows_for(url)[0]
    assert row.status == TaskStatus.SKIPPED
    assert row.status_message == 'Could not resolve this video'


async def test_transient_db_retry_does_not_retire_the_placeholder(test_database, monkeypatch):
    """The retry sits inside the cleanup, so a DB blip must not consume the row.

    Retiring between attempts would leave the successful attempt handing off a SKIPPED row,
    and populate would stand down instead of downloading.
    """
    url = 'https://www.youtube.com/watch?v=ExPaNdEd006'
    task_id = _seed_placeholder(url)
    submitted = {'url': url, 'media_type': 'VIDEO', 'placeholder_task_id': task_id}
    calls = []

    def flaky_filter(jobs):
        calls.append(1)
        if len(calls) == 1:
            statement = 'SELECT 1'
            raise OperationalError(statement, {}, Exception(statement))
        return jobs

    monkeypatch.setattr('orchestrator.retry.time.sleep', lambda _delay: None)
    monkeypatch.setattr('tasks.scheduling.expand_playlists_impl', lambda jobs: jobs)
    monkeypatch.setattr('tasks.media.filter_completed_downloads_impl', flaky_filter)
    fake = FakeOrch()
    monkeypatch.setattr('orchestrator.orch', fake)

    assert run_direct_download_pipeline(None, [submitted]) == {'jobs_started': 1}

    assert len(calls) == 2, 'the transient DB error should have been retried'
    assert _rows_for(url)[0].status == TaskStatus.RESOLVING
    assert fake.specs[0].args[0]['placeholder_task_id'] == task_id


async def test_a_failed_submit_retires_only_the_unclaimed_video(test_database, monkeypatch):
    """Per-video placeholders are minted inside the loop, so they are not in the payload.

    Cleanup keyed off the submission alone would leave the row for a video whose submit
    raised stranded in RESOLVING.
    """
    playlist_task_id = _seed_playlist_placeholder()
    submitted = {
        'url': PLAYLIST_URL,
        'media_type': 'VIDEO',
        'download_playlist': True,
        'placeholder_task_id': playlist_task_id,
    }
    expanded = [{'url': url, 'media_type': 'VIDEO'} for url in VIDEO_URLS]

    class FailsOnSecond(FakeOrch):
        def submit_from_thread(self, spec):
            if self.specs:
                msg = 'lane submit failed'
                raise RuntimeError(msg)
            return super().submit_from_thread(spec)

    monkeypatch.setattr('tasks.scheduling.expand_playlists_impl', lambda _jobs: expanded)
    monkeypatch.setattr('tasks.media.filter_completed_downloads_impl', lambda jobs: jobs)
    monkeypatch.setattr('orchestrator.orch', FailsOnSecond())

    with pytest.raises(RuntimeError):
        run_direct_download_pipeline(None, [submitted])

    handed_off = _rows_for(VIDEO_URLS[0])[0]
    assert handed_off.status == TaskStatus.RESOLVING, 'a queued populate job owns this row'

    stranded = _rows_for(VIDEO_URLS[1])[0]
    assert stranded.status == TaskStatus.SKIPPED
    assert stranded.status_message == 'Could not resolve this video'

    # Already retired with a better reason before the raise, so cleanup left it alone.
    assert _rows_for(PLAYLIST_URL)[0].status_message == 'Expanded into 2 video task(s)'
