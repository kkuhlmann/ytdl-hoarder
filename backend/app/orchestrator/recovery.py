"""Startup recovery and the automatic-retry scheduler.

- run_startup_recovery() rebuilds the lanes from TaskRecord truth at boot
  (QUEUED re-enqueued, IN_PROGRESS resumed), so a restart never loses work.
- retry_scheduler_loop() scans for RETRY rows whose next_retry_at has passed
  and resubmits them (same task_id), then reaps stranded running rows.

Payloads are re-materialized from the DB with the same queries the manual
retry endpoint uses (repositories/task_records/retry.py), just synchronous.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import and_, text
from sqlalchemy.orm import joinedload
from sqlmodel import select

from database import db
from logger import logger
from models import MediaDetails, TaskRecord, TaskStatus, TaskType, utc_now
from progress_publisher import publish_status_change
from repositories import task_records as tr_repo
from serializers import (
    download_job_to_dto,
    media_details_to_dto,
    serialize_download_job,
    serialize_media_details,
)

from .jobs import DOWNLOAD_JOB, POPULATE_JOB, SPRITES_JOB, TRANSCRIPT_JOB, JobSpec
from .retry import TRANSCRIPT_RETRY_POLICY

RETRY_SCAN_INTERVAL_SECONDS = 20.0

# How long a row may sit in a running status with no orchestrator handle before
# the sweep declares it stranded. This is NOT a liveness timeout — a rate-limit
# sleep and a long ffmpeg merge both write nothing for minutes, so updated_at
# says nothing about progress. It only has to outlast the gap between a job's
# status write and the handle snapshot taken by the sweep.
STRANDED_GRACE_SECONDS = 120.0

_STRANDED_STATUSES = (TaskStatus.IN_PROGRESS, TaskStatus.POSTPROCESSING)

# Sanity cap when re-enqueueing interrupted transcripts at startup, so a
# job that crashes the process on every attempt eventually gives up.
_TRANSCRIPT_RESUME_MAX_ATTEMPTS = TRANSCRIPT_RETRY_POLICY.max_retries


# ------------------------------------------------------------------- loaders


def load_download_payload(record: TaskRecord) -> dict | None:
    """Serialized download-job dict for a DOWNLOAD TaskRecord (sync).

    Mirrors retry.py:_fetch_download_job_serialized without HTTP semantics:
    returns None when the MediaDetails/DownloadJob rows are gone.
    """
    with db.sync_session() as session:
        stmt = (
            select(MediaDetails)
            .where(MediaDetails.download_task_record_id == record.id)
            .options(joinedload(MediaDetails.download_jobs))
        )
        media_details = session.execute(stmt).unique().scalar_one_or_none()
        if not media_details or not media_details.download_jobs:
            return None
        dto = download_job_to_dto(media_details.download_jobs[0], media_details=media_details)
        return serialize_download_job(dto)


def load_transcript_payload(record: TaskRecord) -> dict | None:
    """Serialized media-details dict for a TRANSCRIPT TaskRecord (sync)."""
    with db.sync_session() as session:
        stmt = select(MediaDetails).where(MediaDetails.transcript_task_record_id == record.id)
        media_details = session.execute(stmt).scalar_one_or_none()
        if not media_details:
            return None
        return serialize_media_details(media_details_to_dto(media_details))


def load_sprites_payload(record: TaskRecord) -> dict | None:
    """Sprite payload for a SPRITE_GENERATION TaskRecord (sync).

    Resolved from download_job_url + media_type; sprite rows carry no FK back to
    MediaDetails, so this is the same re-resolution DownloadHooks uses.
    """
    with db.sync_session() as session:
        stmt = select(MediaDetails).where(
            and_(
                MediaDetails.url == record.download_job_url,
                MediaDetails.media_type == record.media_type,
            )
        )
        media_details = session.execute(stmt).scalar_one_or_none()
        if not media_details:
            return None
        return {
            'media_details_id': media_details.id,
            'user_id': record.user_id,
            'force': False,
        }


def find_chained_queued_transcript(download_task_id: str) -> TaskRecord | None:
    """The QUEUED transcript chained after a download, if any."""
    with db.sync_session() as session:
        stmt = select(TaskRecord).where(
            and_(
                text('task_records.upstream_task_ids::jsonb ? :upstream_tid'),
                TaskRecord.task_type == TaskType.TRANSCRIPT_GENERATION,
                TaskRecord.status == TaskStatus.QUEUED,
                TaskRecord.deleted_at.is_(None),
            )
        )
        record = session.execute(stmt, {'upstream_tid': download_task_id}).scalars().first()
        if record is not None:
            session.expunge(record)
        return record


def build_download_spec(record: TaskRecord, payload: dict) -> JobSpec:
    """JobSpec for a download TaskRecord, with its chained transcript attached."""
    downstream = None
    transcript = find_chained_queued_transcript(record.task_id)
    if transcript is not None:
        downstream = JobSpec(
            job_name=TRANSCRIPT_JOB,
            task_id=transcript.task_id,
            priority=transcript.priority if transcript.priority is not None else 5,
            queue_sequence=transcript.queue_sequence,
            user_id=transcript.user_id,
        )
    return JobSpec(
        job_name=DOWNLOAD_JOB,
        args=(payload,),
        task_id=record.task_id,
        priority=record.priority if record.priority is not None else 5,
        queue_sequence=record.queue_sequence,
        user_id=record.user_id,
        downstream=downstream,
    )


def build_transcript_spec(record: TaskRecord, payload: dict) -> JobSpec:
    return JobSpec(
        job_name=TRANSCRIPT_JOB,
        args=(payload,),
        task_id=record.task_id,
        priority=record.priority if record.priority is not None else 5,
        queue_sequence=record.queue_sequence,
        user_id=record.user_id,
    )


def build_populate_spec(record: TaskRecord) -> JobSpec:
    """JobSpec resuming the metadata resolution behind a RESOLVING placeholder.

    Deliberately NOT record.task_id: the populate job dispatches the download chain
    from inside itself under that same id, and _submit_nowait would drop the download
    as a duplicate of the still-running populate. The link is the payload's
    placeholder_task_id, which the chain adopts.
    """
    return JobSpec(
        job_name=POPULATE_JOB,
        args=(record.pending_payload,),
        tracked=False,
        priority=record.priority if record.priority is not None else 5,
        user_id=record.user_id,
    )


def build_sprites_spec(record: TaskRecord, payload: dict) -> JobSpec:
    return JobSpec(
        job_name=SPRITES_JOB,
        args=(payload,),
        task_id=record.task_id,
        priority=record.priority if record.priority is not None else 5,
        queue_sequence=record.queue_sequence,
        user_id=record.user_id,
    )


# ---------------------------------------------------------------- recovery


def _pending_records() -> list[TaskRecord]:
    with db.sync_session() as session:
        stmt = select(TaskRecord).where(
            and_(
                TaskRecord.status.in_(
                    [
                        TaskStatus.RESOLVING,
                        TaskStatus.QUEUED,
                        TaskStatus.IN_PROGRESS,
                        TaskStatus.POSTPROCESSING,
                        TaskStatus.RETRY,
                    ]
                ),
                TaskRecord.deleted_at.is_(None),
            )
        )
        records = list(session.execute(stmt).scalars().all())
        for record in records:
            session.expunge(record)
        return records


def _mark_unrecoverable(record: TaskRecord, message: str) -> None:
    tr_repo.sync_update_one(
        record.task_id, {'status': TaskStatus.FAILED, 'status_message': message}
    )
    tr_repo.sync_mark_downstream_as_failed(record.task_id)


def _cancel_on_purge(record: TaskRecord) -> None:
    tr_repo.sync_update_one(
        record.task_id,
        {
            'status': TaskStatus.CANCELLED,
            'status_message': 'Cleared on startup (tasks.purge_on_startup)',
        },
    )


def run_startup_recovery(orch, purge: bool = False) -> dict:  # noqa: C901 — one pass over every resumable TaskRecord status; the branches are the status matrix
    """Rebuild lanes from TaskRecord truth. Sync — call via asyncio.to_thread.

    Policy by (task_type, status):
    - purge=True → everything pending becomes CANCELLED (tasks.purge_on_startup:
      the development "clean slate on boot" mode).
    - RESOLVING placeholders → the populate job is re-submitted from the row's
      pending_payload (FAILED if it has none), so a restart between submit and the
      yt-dlp metadata fetch doesn't lose the download.
    - DOWNLOAD QUEUED / IN_PROGRESS / POSTPROCESSING → re-enqueued (yt-dlp
      resumes .part files); interrupted rows are reset to QUEUED first.
    - TRANSCRIPT QUEUED (upstream complete/absent) → re-enqueued standalone;
      chained-QUEUED transcripts ride along as their download's downstream.
    - TRANSCRIPT IN_PROGRESS → partial blocks deleted, re-enqueued with
      retry_count+1 (FAILED past the transcript retry policy).
    - CLIP QUEUED / IN_PROGRESS → FAILED (quick, user-interactive jobs; the UI
      retry button re-dispatches them cleanly).
    - SPRITE QUEUED / IN_PROGRESS → re-enqueued (cheap and idempotent; partial
      output is deleted first), unless its download hasn't completed — those are
      chain rows awaiting DownloadHooks.on_success. Nothing else would ever
      retrigger a sprite job, so a dropped one means no scrub previews, ever.
    - RETRY rows → left for the retry scheduler (next_retry_at drives them).
    - NOT_READY placeholders → untouched.
    """
    from repositories import transcript_blocks as tb_repo

    stats = {'resumed': 0, 'failed': 0, 'cancelled': 0, 'left_for_retry': 0}
    records = _pending_records()
    if not records:
        logger.info('Startup recovery: no pending tasks')
        return stats

    # Downloads first so chained transcripts attach as downstream, not standalone.
    records.sort(key=lambda r: (r.task_type != TaskType.DOWNLOAD, r.queue_sequence or 0))
    chained_transcript_ids: set[str] = set()

    for record in records:
        if purge:
            _cancel_on_purge(record)
            stats['cancelled'] += 1
            continue

        if record.status == TaskStatus.RETRY:
            stats['left_for_retry'] += 1
            continue

        # Before the DOWNLOAD branch: a placeholder has no MediaDetails yet, so
        # load_download_payload would return None and fail a perfectly resumable row.
        if record.status == TaskStatus.RESOLVING:
            if record.pending_payload is None:
                _mark_unrecoverable(record, 'Interrupted before metadata was fetched')
                stats['failed'] += 1
                continue
            orch.submit_from_thread(build_populate_spec(record))
            stats['resumed'] += 1
            continue

        if record.task_type == TaskType.DOWNLOAD:
            payload = load_download_payload(record)
            if payload is None:
                _mark_unrecoverable(record, 'Could not re-load job data after restart')
                stats['failed'] += 1
                continue
            if record.status in (TaskStatus.IN_PROGRESS, TaskStatus.POSTPROCESSING):
                tr_repo.sync_update_one(
                    record.task_id,
                    {
                        'status': TaskStatus.QUEUED,
                        'status_message': 'Resumed after restart',
                        'download_phase': None,
                    },
                )
            spec = build_download_spec(record, payload)
            if spec.downstream is not None:
                chained_transcript_ids.add(spec.downstream.task_id)
            orch.submit_from_thread(spec)
            stats['resumed'] += 1

        elif record.task_type == TaskType.TRANSCRIPT_GENERATION:
            if record.task_id in chained_transcript_ids:
                continue  # rides along as its download's downstream
            if record.status == TaskStatus.QUEUED and _upstream_still_pending(record):
                # Upstream download wasn't recoverable as a chain head (e.g. it
                # is in RETRY) — leave the transcript queued; it re-dispatches
                # when its upstream is retried.
                continue
            payload = load_transcript_payload(record)
            if payload is None:
                _mark_unrecoverable(record, 'Could not re-load job data after restart')
                stats['failed'] += 1
                continue
            if record.status == TaskStatus.IN_PROGRESS:
                media_id = _media_id_for_transcript(record)
                if media_id is not None:
                    tb_repo.sync_delete_transcript_block_by_media_details_id(media_id)
                if record.retry_count >= _TRANSCRIPT_RESUME_MAX_ATTEMPTS:
                    _mark_unrecoverable(
                        record, 'Interrupted too many times; giving up after restart'
                    )
                    stats['failed'] += 1
                    continue
                tr_repo.sync_update_one(
                    record.task_id,
                    {
                        'status': TaskStatus.QUEUED,
                        'status_message': 'Resumed after restart',
                        'percent_complete': 0,
                        'retry_count': record.retry_count + 1,
                    },
                )
            orch.submit_from_thread(build_transcript_spec(record, payload))
            stats['resumed'] += 1

        elif record.task_type == TaskType.CLIP_GENERATION:
            _mark_unrecoverable(record, 'Interrupted by restart — retry to re-create the clip')
            stats['failed'] += 1

        elif record.task_type == TaskType.SPRITE_GENERATION:
            if record.status == TaskStatus.QUEUED and _upstream_still_pending(record):
                # Its download re-dispatches it via DownloadHooks.on_success. Running
                # now would tile a file that isn't on disk yet.
                continue
            payload = load_sprites_payload(record)
            if payload is None:
                _mark_unrecoverable(record, 'Could not re-load job data after restart')
                stats['failed'] += 1
                continue
            if record.status in (TaskStatus.IN_PROGRESS, TaskStatus.POSTPROCESSING):
                from tasks.sprites import delete_partial_sprite_output

                delete_partial_sprite_output(payload['media_details_id'])
                tr_repo.sync_update_one(
                    record.task_id,
                    {'status': TaskStatus.QUEUED, 'status_message': 'Resumed after restart'},
                )
            if record.queue_sequence is None:
                # Crashed between the download's COMPLETE write and the sprite submit.
                record.queue_sequence = tr_repo.sync_get_next_queue_sequence()
                tr_repo.sync_update_one(record.task_id, {'queue_sequence': record.queue_sequence})
            orch.submit_from_thread(build_sprites_spec(record, payload))
            stats['resumed'] += 1

        else:
            _mark_unrecoverable(record, 'Interrupted by restart')
            stats['failed'] += 1

    logger.info(
        f'Startup recovery: resumed={stats["resumed"]} failed={stats["failed"]} '
        f'cancelled={stats["cancelled"]} left_for_retry={stats["left_for_retry"]}'
    )
    return stats


def _upstream_still_pending(record: TaskRecord) -> bool:
    if not record.upstream_task_ids:
        return False
    with db.sync_session() as session:
        stmt = select(TaskRecord).where(TaskRecord.task_id.in_(record.upstream_task_ids))
        upstream = session.execute(stmt).scalars().all()
        return any(u.status != TaskStatus.COMPLETE for u in upstream)


def _media_id_for_transcript(record: TaskRecord) -> int | None:
    with db.sync_session() as session:
        stmt = select(MediaDetails.id).where(MediaDetails.transcript_task_record_id == record.id)
        return session.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------- retry scheduler


def _find_due_retries() -> list[TaskRecord]:
    with db.sync_session() as session:
        stmt = select(TaskRecord).where(
            and_(
                TaskRecord.status == TaskStatus.RETRY,
                TaskRecord.next_retry_at.is_not(None),
                TaskRecord.next_retry_at <= utc_now(),
                TaskRecord.deleted_at.is_(None),
            )
        )
        records = list(session.execute(stmt).scalars().all())
        for record in records:
            session.expunge(record)
        return records


def resubmit_due_retry(orch, record: TaskRecord) -> bool:
    """Resubmit one due RETRY row (same task_id, so the attempt counter carries)."""
    if record.task_type == TaskType.DOWNLOAD:
        payload = load_download_payload(record)
        build = build_download_spec
    elif record.task_type == TaskType.TRANSCRIPT_GENERATION:
        payload = load_transcript_payload(record)
        build = build_transcript_spec
    else:
        _mark_unrecoverable(record, 'Automatic retry not supported for this task type')
        return False

    if payload is None:
        _mark_unrecoverable(record, 'Could not re-load job data for retry')
        return False

    # Clear next_retry_at BEFORE enqueueing so the next scan can't double-fire.
    tr_repo.sync_update_one(record.task_id, {'next_retry_at': None})
    orch.submit_from_thread(build(record, payload))
    logger.info(f'Retry scheduler: resubmitted {record.task_type} task {record.task_id}')
    return True


def process_due_retries(orch) -> int:
    """One scan-and-resubmit pass. Sync — called via asyncio.to_thread."""
    count = 0
    for record in _find_due_retries():
        try:
            if resubmit_due_retry(orch, record):
                count += 1
        except Exception:
            logger.exception(f'Retry scheduler failed for {record.task_id}')
    return count


# ------------------------------------------------------- stranded-row sweep


def _find_stranded_records(active_task_ids: set[str], grace: float) -> list[TaskRecord]:
    cutoff = utc_now() - timedelta(seconds=grace)
    with db.sync_session() as session:
        stmt = select(TaskRecord).where(
            and_(
                TaskRecord.status.in_(_STRANDED_STATUSES),
                TaskRecord.updated_at < cutoff,
                TaskRecord.deleted_at.is_(None),
            )
        )
        records = [
            record
            for record in session.execute(stmt).scalars().all()
            if record.task_id not in active_task_ids
        ]
        for record in records:
            session.expunge(record)
        return records


def reap_stranded_records(active_task_ids: set[str], grace: float = STRANDED_GRACE_SECONDS) -> int:
    """Fail rows still marked running whose job already left its lane.

    before_start (orchestrator.hooks) and the yt-dlp postprocessor hook are the
    only writers of IN_PROGRESS/POSTPROCESSING, and both run inside run_job_sync
    while the orchestrator holds a handle. So a row in one of those statuses with
    no handle has nothing behind it: the wrapper's terminal reconcile could not
    reach the DB (a full disk will do it), and without this sweep the row spins
    in the tasks table — indistinguishable from a live download — until the next
    restart hands it to startup recovery.

    Sync — called via asyncio.to_thread with a set snapshotted on the loop.
    """
    count = 0
    message = 'Task ended without reporting a final status'
    for record in _find_stranded_records(active_task_ids, grace):
        try:
            tr_repo.sync_update_one(
                record.task_id, {'status': TaskStatus.FAILED, 'status_message': message}
            )
            tr_repo.sync_mark_downstream_as_failed(record.task_id)
            publish_status_change(
                record.task_id, TaskStatus.FAILED.value, message, user_id=record.user_id
            )
            logger.warning(f'Reaped stranded {record.task_type.value} task {record.task_id}')
            count += 1
        except Exception:
            logger.exception(f'Could not reap stranded task {record.task_id}')
    return count


async def retry_scheduler_loop(orch, interval: float = RETRY_SCAN_INTERVAL_SECONDS) -> None:
    """Background service: resubmit due RETRY rows, then reap stranded ones."""
    while orch.running:
        try:
            await asyncio.to_thread(process_due_retries, orch)
            # Snapshot the handles here: _handles is only safe to read on the loop.
            active_task_ids = orch.active_task_ids()
            await asyncio.to_thread(reap_stranded_records, active_task_ids)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception('Retry scheduler scan failed')
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
