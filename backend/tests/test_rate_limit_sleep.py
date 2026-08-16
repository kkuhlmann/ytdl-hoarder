"""Tests for the pre-download rate-limit sleep and the deadline it publishes.

`download_sleep_seconds` parks subscription and playlist downloads before they start
transferring. The row stays IN_PROGRESS throughout — "Sleeping" is a display state the
UI derives from `sleep_until`, not a TaskStatus — so the wake time is the only thing
telling a client the difference between a job that is waiting and one that is working.

It is an absolute deadline on purpose: the countdown has to keep ticking between SSE
events and come back correct after a page reload, neither of which a remaining-seconds
count can do.
"""

import uuid
from datetime import timedelta

import pytest
from sqlmodel import select

from database import db
from models import AppSettings, JobType, MediaType, TaskRecord, TaskStatus, TaskType, utc_now
from orchestrator import JobCancelled, JobContext
from schemas import DownloadJobDTO
from tasks.downloads import SLEEP_STATUS_MESSAGE, _rate_limit_sleep

URL = 'https://www.youtube.com/watch?v=SlEePiNg0001'


def _seed_task() -> str:
    task_id = str(uuid.uuid4())
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.IN_PROGRESS,
                status_message='Starting download...',
                media_type=MediaType.VIDEO,
                download_job_url=URL,
            )
        )
        session.commit()
    finally:
        session.close()
    return task_id


def _reload(task_id: str) -> TaskRecord:
    session = db.get_sync_session()
    try:
        return (
            session.execute(select(TaskRecord).where(TaskRecord.task_id == task_id)).scalars().one()
        )
    finally:
        session.close()


def _dto(job_type: JobType) -> DownloadJobDTO:
    return DownloadJobDTO(url=URL, media_type=MediaType.VIDEO, job_type=job_type)


@pytest.fixture
def sleep_seconds(monkeypatch):
    """Set download_sleep_seconds, returning a setter so each test picks its own."""

    def _set(value: int) -> None:
        monkeypatch.setattr(
            'tasks.downloads.settings_repo.sync_get_settings',
            lambda: AppSettings(download_sleep_seconds=value),
        )

    return _set


@pytest.fixture
def captured_events(monkeypatch):
    """Record every status_change the sleep publishes, plus the row as it was published."""
    events = []

    def _capture(task_id, status, message='', user_id=None, fields=None):
        events.append(
            {
                'status': status,
                'message': message,
                'fields': fields,
                'row': _reload(task_id),
            }
        )
        return True

    monkeypatch.setattr('tasks.downloads.publish_status_change', _capture)
    return events


def test_sleep_persists_and_publishes_the_same_wake_time(
    test_database, sleep_seconds, captured_events
):
    sleep_seconds(1)
    task_id = _seed_task()

    started = utc_now()
    _rate_limit_sleep(JobContext(task_id), task_id, _dto(JobType.CHANNEL_SUBSCRIPTION))

    assert len(captured_events) == 1
    event = captured_events[0]
    assert event['status'] == TaskStatus.IN_PROGRESS.value
    assert event['message'] == SLEEP_STATUS_MESSAGE
    assert event['row'].status_message == SLEEP_STATUS_MESSAGE

    # The client can only render a countdown if the deadline reaches it, and can only
    # trust it if the row it later refetches agrees. Both are read as of publish time —
    # by the time this assertion runs the sleep is over and the deadline has passed.
    deadline = event['row'].sleep_until
    assert event['fields']['sleep_until'] == deadline.isoformat()
    assert timedelta(0) < deadline - started <= timedelta(seconds=3)


def test_wake_clears_the_deadline(test_database, sleep_seconds, captured_events):
    sleep_seconds(1)
    task_id = _seed_task()

    _rate_limit_sleep(JobContext(task_id), task_id, _dto(JobType.PLAYLIST_DOWNLOAD))

    assert _reload(task_id).sleep_until is None, 'a woken row must not still look asleep'


def test_cancel_during_the_sleep_leaves_the_deadline_behind(
    test_database, sleep_seconds, captured_events
):
    """Deliberate: the display state is gated on IN_PROGRESS, so a CANCELLED row is inert."""
    sleep_seconds(60)
    task_id = _seed_task()
    ctx = JobContext(task_id)
    ctx.cancel_event.set()

    with pytest.raises(JobCancelled):
        _rate_limit_sleep(ctx, task_id, _dto(JobType.PLAYLIST_SUBSCRIPTION))

    assert ctx.skip_downstream is True
    assert _reload(task_id).sleep_until is not None


def test_a_one_off_download_never_sleeps(test_database, sleep_seconds, captured_events):
    sleep_seconds(60)
    task_id = _seed_task()

    _rate_limit_sleep(JobContext(task_id), task_id, _dto(JobType.NORMAL_DOWNLOAD))

    assert captured_events == []
    assert _reload(task_id).sleep_until is None


def test_zero_sleep_seconds_never_sleeps(test_database, sleep_seconds, captured_events):
    sleep_seconds(0)
    task_id = _seed_task()

    _rate_limit_sleep(JobContext(task_id), task_id, _dto(JobType.CHANNEL_SUBSCRIPTION))

    assert captured_events == []
    assert _reload(task_id).sleep_until is None
