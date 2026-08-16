"""Startup recovery + retry scheduler: rebuilding lanes from TaskRecord truth."""

from datetime import timedelta

from database import db
from models import (
    DownloadJob,
    JobType,
    MediaDetails,
    MediaType,
    TaskRecord,
    TaskStatus,
    TaskType,
    utc_now,
)
from orchestrator import DOWNLOAD_JOB, POPULATE_JOB, SPRITES_JOB, TRANSCRIPT_JOB
from orchestrator.recovery import process_due_retries, run_startup_recovery
from repositories import task_records as tr_repo


class FakeOrch:
    """Captures submissions without running anything."""

    def __init__(self):
        self.specs = []

    def submit_from_thread(self, spec):
        self.specs.append(spec)
        return spec.task_id

    def spec_for(self, task_id):
        return next((s for s in self.specs if s.task_id == task_id), None)


def _insert_download_rows(
    task_id: str,
    status: TaskStatus,
    *,
    url_key: str,
    queue_sequence: int | None = 100,
    priority: int = 5,
    with_transcript: TaskStatus | None = None,
    with_job: bool = True,
) -> None:
    """Insert a download TaskRecord with linked MediaDetails + DownloadJob."""
    url = f'https://www.youtube.com/watch?v={url_key}'
    session = db.get_sync_session()
    try:
        task = TaskRecord(
            task_id=task_id,
            task_type=TaskType.DOWNLOAD,
            status=status,
            title=f'Recovery {url_key}',
            channel='Recovery Channel',
            media_type=MediaType.AUDIO,
            download_job_url=url,
            queue_sequence=queue_sequence,
            priority=priority,
        )
        session.add(task)
        session.flush()

        md = MediaDetails(
            url=url,
            media_type=MediaType.AUDIO,
            channel='Recovery Channel',
            title=f'Recovery {url_key}',
            status=status,
            download_task_record_id=task.id,
        )
        session.add(md)
        session.flush()

        if with_job:
            session.add(
                DownloadJob(
                    url=url,
                    audio_only=True,
                    download_playlist=False,
                    overwrite=False,
                    media_type=MediaType.AUDIO,
                    job_type=JobType.NORMAL_DOWNLOAD,
                    media_details_id=md.id,
                )
            )

        if with_transcript is not None:
            session.add(
                TaskRecord(
                    task_id=f'{task_id}-transcript',
                    task_type=TaskType.TRANSCRIPT_GENERATION,
                    status=with_transcript,
                    upstream_task_ids=[task_id],
                    download_job_url=url,
                    media_type=MediaType.AUDIO,
                )
            )
        session.commit()
    finally:
        session.close()


def _insert_transcript_rows(
    task_id: str, status: TaskStatus, *, url_key: str, retry_count: int = 0
) -> int:
    """Insert a transcript TaskRecord with linked MediaDetails. Returns media id."""
    url = f'https://www.youtube.com/watch?v={url_key}'
    session = db.get_sync_session()
    try:
        task = TaskRecord(
            task_id=task_id,
            task_type=TaskType.TRANSCRIPT_GENERATION,
            status=status,
            title=f'Recovery {url_key}',
            channel='Recovery Channel',
            media_type=MediaType.AUDIO,
            retry_count=retry_count,
        )
        session.add(task)
        session.flush()

        md = MediaDetails(
            url=url,
            media_type=MediaType.AUDIO,
            channel='Recovery Channel',
            title=f'Recovery {url_key}',
            transcript_task_record_id=task.id,
        )
        session.add(md)
        session.flush()
        media_id = md.id
        session.commit()
        return media_id
    finally:
        session.close()


def _status_of(task_id: str) -> TaskStatus:
    return tr_repo.sync_get_task_by_task_id(task_id).status


def test_queued_download_is_reenqueued_with_chained_transcript(test_database):
    _insert_download_rows(
        'rec-dl-queued',
        TaskStatus.QUEUED,
        url_key='recQueued01',
        with_transcript=TaskStatus.QUEUED,
    )
    fake = FakeOrch()
    stats = run_startup_recovery(fake)

    assert stats['resumed'] == 1
    spec = fake.spec_for('rec-dl-queued')
    assert spec is not None
    assert spec.job_name == DOWNLOAD_JOB
    assert spec.queue_sequence == 100
    assert spec.downstream is not None
    assert spec.downstream.task_id == 'rec-dl-queued-transcript'
    assert spec.downstream.job_name == TRANSCRIPT_JOB
    # The chained transcript must NOT also be enqueued standalone
    assert fake.spec_for('rec-dl-queued-transcript') is None


def test_in_progress_download_is_reset_and_resumed(test_database):
    _insert_download_rows('rec-dl-running', TaskStatus.IN_PROGRESS, url_key='recRunning1')
    fake = FakeOrch()
    run_startup_recovery(fake)

    assert fake.spec_for('rec-dl-running') is not None
    record = tr_repo.sync_get_task_by_task_id('rec-dl-running')
    assert record.status == TaskStatus.QUEUED
    assert record.status_message == 'Resumed after restart'


def test_download_without_job_rows_is_marked_failed(test_database):
    _insert_download_rows('rec-dl-orphan', TaskStatus.QUEUED, url_key='recOrphan01', with_job=False)
    fake = FakeOrch()
    stats = run_startup_recovery(fake)

    # (Conftest pre-populates other unlinked QUEUED rows, so assert on ours.)
    assert stats['failed'] >= 1
    assert fake.spec_for('rec-dl-orphan') is None
    assert _status_of('rec-dl-orphan') == TaskStatus.FAILED


def test_in_progress_transcript_resumes_with_bumped_retry_count(test_database):
    from repositories import transcript_blocks as tb_repo

    _insert_transcript_rows('rec-tr-running', TaskStatus.IN_PROGRESS, url_key='recTrRun01')
    fake = FakeOrch()
    run_startup_recovery(fake)

    spec = fake.spec_for('rec-tr-running')
    assert spec is not None and spec.job_name == TRANSCRIPT_JOB
    record = tr_repo.sync_get_task_by_task_id('rec-tr-running')
    assert record.status == TaskStatus.QUEUED
    assert record.retry_count == 1
    # tb_repo cleanup ran (no blocks existed — just verifying no crash)
    assert tb_repo is not None


def test_in_progress_transcript_past_retry_budget_fails(test_database):
    _insert_transcript_rows(
        'rec-tr-exhausted', TaskStatus.IN_PROGRESS, url_key='recTrExh01', retry_count=5
    )
    fake = FakeOrch()
    run_startup_recovery(fake)

    assert fake.spec_for('rec-tr-exhausted') is None
    assert _status_of('rec-tr-exhausted') == TaskStatus.FAILED


def test_clip_tasks_fail_on_restart(test_database):
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id='rec-clip-running',
                task_type=TaskType.CLIP_GENERATION,
                status=TaskStatus.IN_PROGRESS,
            )
        )
        session.commit()
    finally:
        session.close()

    fake = FakeOrch()
    run_startup_recovery(fake)
    assert _status_of('rec-clip-running') == TaskStatus.FAILED


def test_purge_cancels_everything_pending(test_database):
    _insert_download_rows('rec-purge-dl', TaskStatus.QUEUED, url_key='recPurge01')
    _insert_transcript_rows('rec-purge-tr', TaskStatus.IN_PROGRESS, url_key='recPurge02')

    fake = FakeOrch()
    stats = run_startup_recovery(fake, purge=True)

    assert stats['cancelled'] >= 2
    assert fake.specs == []
    assert _status_of('rec-purge-dl') == TaskStatus.CANCELLED
    assert _status_of('rec-purge-tr') == TaskStatus.CANCELLED


def test_not_ready_placeholders_are_untouched(test_database):
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id='rec-not-ready',
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.NOT_READY,
                download_job_url='https://www.youtube.com/watch?v=recNR01',
                media_type=MediaType.AUDIO,
            )
        )
        session.commit()
    finally:
        session.close()

    fake = FakeOrch()
    run_startup_recovery(fake)
    assert _status_of('rec-not-ready') == TaskStatus.NOT_READY
    assert fake.specs == []


def test_retry_rows_are_left_for_the_retry_scheduler(test_database):
    _insert_download_rows('rec-dl-retry', TaskStatus.RETRY, url_key='recRetry01')
    tr_repo.sync_update_one(
        'rec-dl-retry', {'next_retry_at': utc_now() + timedelta(hours=1), 'retry_count': 2}
    )

    fake = FakeOrch()
    stats = run_startup_recovery(fake)
    assert stats['left_for_retry'] == 1
    assert fake.specs == []
    assert _status_of('rec-dl-retry') == TaskStatus.RETRY


# --- retry scheduler ---


def test_due_retry_is_resubmitted_with_same_task_id(test_database):
    _insert_download_rows('rec-due-retry', TaskStatus.RETRY, url_key='recDue0001')
    tr_repo.sync_update_one(
        'rec-due-retry', {'next_retry_at': utc_now() - timedelta(seconds=5), 'retry_count': 3}
    )

    fake = FakeOrch()
    count = process_due_retries(fake)

    assert count == 1
    spec = fake.spec_for('rec-due-retry')
    assert spec is not None
    assert spec.job_name == DOWNLOAD_JOB
    # next_retry_at cleared so the next scan can't double-fire
    record = tr_repo.sync_get_task_by_task_id('rec-due-retry')
    assert record.next_retry_at is None
    assert record.retry_count == 3, 'attempt counter untouched by the scheduler'


def test_future_retry_is_not_resubmitted(test_database):
    _insert_download_rows('rec-future-retry', TaskStatus.RETRY, url_key='recFut0001')
    tr_repo.sync_update_one('rec-future-retry', {'next_retry_at': utc_now() + timedelta(hours=2)})

    fake = FakeOrch()
    assert process_due_retries(fake) == 0
    assert fake.specs == []


def test_retry_without_next_retry_at_is_ignored(test_database):
    # A RETRY row carrying no next_retry_at is never due, so it waits for a manual retry.
    _insert_download_rows('rec-no-retry-at', TaskStatus.RETRY, url_key='recLeg0001')

    fake = FakeOrch()
    assert process_due_retries(fake) == 0
    assert fake.specs == []


def test_due_retry_with_missing_payload_fails(test_database):
    _insert_download_rows(
        'rec-broken-retry', TaskStatus.RETRY, url_key='recBrk0001', with_job=False
    )
    tr_repo.sync_update_one('rec-broken-retry', {'next_retry_at': utc_now() - timedelta(seconds=5)})

    fake = FakeOrch()
    assert process_due_retries(fake) == 0
    assert _status_of('rec-broken-retry') == TaskStatus.FAILED


# --- sprite recovery ---
# Re-enqueued rather than failed: nothing else ever retriggers sprite generation,
# so a dropped job means that video permanently has no scrub previews.


def _insert_sprite_rows(task_id: str, status: TaskStatus, *, url_key: str, with_media=True) -> None:
    url = f'https://youtube.com/watch?v={url_key}'
    session = db.get_sync_session()
    try:
        if with_media:
            session.add(
                MediaDetails(
                    url=url,
                    media_type=MediaType.VIDEO,
                    title='Sprite Video',
                    file_path=f'/tmp/{url_key}.mp4',
                    duration=1800.0,
                )
            )
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type=TaskType.SPRITE_GENERATION,
                status=status,
                download_job_url=url,
                media_type=MediaType.VIDEO,
                queue_sequence=200,
                priority=5,
            )
        )
        session.commit()
    finally:
        session.close()


def test_queued_sprite_is_reenqueued(test_database):
    _insert_sprite_rows('rec-spr-queued', TaskStatus.QUEUED, url_key='recSpr01')
    fake = FakeOrch()
    run_startup_recovery(fake)

    spec = fake.spec_for('rec-spr-queued')
    assert spec is not None
    assert spec.job_name == SPRITES_JOB
    assert spec.args[0]['force'] is False


def test_in_progress_sprite_is_reset_and_reenqueued(test_database):
    _insert_sprite_rows('rec-spr-running', TaskStatus.IN_PROGRESS, url_key='recSpr02')
    fake = FakeOrch()
    run_startup_recovery(fake)

    assert fake.spec_for('rec-spr-running') is not None
    assert _status_of('rec-spr-running') == TaskStatus.QUEUED


def test_sprite_without_media_fails(test_database):
    _insert_sprite_rows('rec-spr-orphan', TaskStatus.QUEUED, url_key='recSpr03', with_media=False)
    fake = FakeOrch()
    run_startup_recovery(fake)

    assert fake.spec_for('rec-spr-orphan') is None
    assert _status_of('rec-spr-orphan') == TaskStatus.FAILED


def _insert_sprite_with_upstream(
    task_id: str, *, url_key: str, download_status: TaskStatus, queue_sequence: int | None
) -> None:
    """Chain-shaped sprite row: carries upstream_task_ids like populate time creates it.

    The download row must be fully wired (MediaDetails FK + DownloadJob) or recovery
    rules it unrecoverable and fails the whole chain, sprite included.
    """
    dl_task_id = f'{task_id}-dl'
    _insert_download_rows(dl_task_id, download_status, url_key=url_key)

    url = f'https://www.youtube.com/watch?v={url_key}'
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type=TaskType.SPRITE_GENERATION,
                status=TaskStatus.QUEUED,
                download_job_url=url,
                media_type=MediaType.AUDIO,
                upstream_task_ids=[dl_task_id],
                queue_sequence=queue_sequence,
            )
        )
        session.commit()
    finally:
        session.close()


def test_sprite_waiting_on_its_download_is_left_alone(test_database):
    """Running it now would tile a file that isn't on disk yet."""
    _insert_sprite_with_upstream(
        'rec-spr-waiting',
        url_key='recSprW01',
        download_status=TaskStatus.QUEUED,
        queue_sequence=None,
    )
    fake = FakeOrch()
    run_startup_recovery(fake)

    assert fake.spec_for('rec-spr-waiting') is None
    assert _status_of('rec-spr-waiting') == TaskStatus.QUEUED


def test_undispatched_sprite_with_complete_download_is_dispatched(test_database):
    """The crash window between the download's COMPLETE write and the sprite submit."""
    _insert_sprite_with_upstream(
        'rec-spr-undispatched',
        url_key='recSprU01',
        download_status=TaskStatus.COMPLETE,
        queue_sequence=None,
    )
    fake = FakeOrch()
    run_startup_recovery(fake)

    assert fake.spec_for('rec-spr-undispatched') is not None
    session = db.get_sync_session()
    try:
        row = session.query(TaskRecord).filter_by(task_id='rec-spr-undispatched').one()
        assert row.queue_sequence is not None
    finally:
        session.close()


def test_dispatched_sprite_is_still_reenqueued(test_database):
    _insert_sprite_with_upstream(
        'rec-spr-dispatched',
        url_key='recSprD01',
        download_status=TaskStatus.COMPLETE,
        queue_sequence=300,
    )
    fake = FakeOrch()
    run_startup_recovery(fake)

    assert fake.spec_for('rec-spr-dispatched') is not None


def _insert_resolving_placeholder(task_id: str, url_key: str, *, with_payload: bool) -> None:
    url = f'https://www.youtube.com/watch?v={url_key}'
    payload = {'url': url, 'media_type': 'AUDIO', 'placeholder_task_id': task_id}
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.RESOLVING,
                title=url,
                media_type=MediaType.AUDIO,
                download_job_url=url,
                priority=1,
                pending_payload=payload if with_payload else None,
            )
        )
        session.commit()
    finally:
        session.close()


def test_resolving_placeholder_resumes_its_populate_job(test_database):
    """A restart between submit and the metadata fetch must not lose the download."""
    _insert_resolving_placeholder('rec-resolving', 'recResolv01', with_payload=True)
    fake = FakeOrch()
    run_startup_recovery(fake)

    spec = next(s for s in fake.specs if s.job_name == POPULATE_JOB)
    # Never the placeholder's own id: the populate job dispatches the download chain
    # under that id from inside itself, and _submit_nowait would drop it as a duplicate.
    assert spec.task_id != 'rec-resolving'
    assert spec.args[0]['placeholder_task_id'] == 'rec-resolving'
    assert _status_of('rec-resolving') == TaskStatus.RESOLVING


def test_resolving_placeholder_without_payload_fails(test_database):
    _insert_resolving_placeholder('rec-resolving-bare', 'recResolv02', with_payload=False)
    fake = FakeOrch()
    run_startup_recovery(fake)

    assert not [s for s in fake.specs if s.job_name == POPULATE_JOB]
    assert _status_of('rec-resolving-bare') == TaskStatus.FAILED


def test_resolving_placeholder_is_cancelled_on_purge(test_database):
    _insert_resolving_placeholder('rec-resolving-purge', 'recResolv03', with_payload=True)
    fake = FakeOrch()
    run_startup_recovery(fake, purge=True)

    assert fake.specs == []
    assert _status_of('rec-resolving-purge') == TaskStatus.CANCELLED
