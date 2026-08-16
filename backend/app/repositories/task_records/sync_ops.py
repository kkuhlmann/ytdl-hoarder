# --- Sync functions (job bodies run in lane threads / the ML child) ---


from sqlalchemy import and_, delete, update
from sqlmodel import select

from database import db
from logger import logger
from models import TASK_QUEUE_SEQUENCE, TaskRecord, TaskStatus, TaskType, utc_now

from .statements import mark_downstream_stmt


def sync_insert_task(task: TaskRecord) -> TaskRecord:
    """Sync version: Insert a new task record."""
    with db.sync_session() as session:
        session.add(task)
        session.flush()
        session.refresh(task)
        return task


def sync_insert_many_tasks(tasks: list[TaskRecord]) -> list[int]:
    """Sync version: Insert multiple task records."""
    with db.sync_session() as session:
        session.add_all(tasks)
        session.flush()
        # IDs are populated on model instances after flush
        return [task.id for task in tasks]


def sync_delete_tasks_by_ids(ids: list[int]) -> int:
    """Sync version: Hard-delete task records by primary-key id.

    Used to roll back task records that were just inserted when a later step in
    the same download-chain persistence fails (e.g. the download_jobs insert
    hits a FK violation), so no orphaned QUEUED rows are left behind.
    """
    if not ids:
        return 0
    with db.sync_session() as session:
        stmt = delete(TaskRecord).where(TaskRecord.id.in_(ids))
        result = session.execute(stmt)
        return result.rowcount


def sync_update_one(task_id: str, updated_fields: dict) -> TaskRecord | None:
    """Sync version: Update a task record by task_id."""
    with db.sync_session() as session:
        stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
        result = session.execute(stmt)
        task = result.scalar_one_or_none()

        if not task:
            logger.warning(
                f'sync_update_one: no TaskRecord found for task_id={task_id}, '
                f'fields={list(updated_fields.keys())}'
            )
            return None

        # Copy to avoid mutating caller's dict (e.g. adding datetime to a dict
        # that will later be passed to json.dumps in publish_progress)
        updated_fields = {**updated_fields}
        updated_fields.setdefault('updated_at', utc_now())

        for key, value in updated_fields.items():
            if hasattr(task, key):
                setattr(task, key, value)

        session.flush()
        session.refresh(task)
        return task


def sync_get_task_by_task_id(task_id: str) -> TaskRecord | None:
    """Sync version: Get a task by its task_id."""
    with db.sync_session() as session:
        stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
        result = session.execute(stmt)
        return result.scalar_one_or_none()


def sync_find_one(filter_params: dict) -> TaskRecord | None:
    """Sync version: Find a single task matching the filter params.

    Supports both equality checks and 'in' queries:
    - Single values: {'status': TaskStatus.QUEUED} -> status == QUEUED
    - List values: {'status': [TaskStatus.QUEUED, TaskStatus.IN_PROGRESS]} -> status IN (...)

    Soft-deleted rows never match; if several rows qualify the newest wins. Callers
    filter on status sets wider than ix_task_records_active_unique's predicate
    (POSTPROCESSING is not in it), so multiple matches are a legal state, not an error.
    """
    with db.sync_session() as session:
        stmt = select(TaskRecord)
        conditions = [TaskRecord.deleted_at.is_(None)]

        for key, value in filter_params.items():
            if hasattr(TaskRecord, key):
                column = getattr(TaskRecord, key)
                if isinstance(value, list):
                    conditions.append(column.in_(value))
                else:
                    conditions.append(column == value)

        stmt = stmt.where(and_(*conditions)).order_by(TaskRecord.id.desc()).limit(1)

        result = session.execute(stmt)
        return result.scalars().first()


def sync_mark_downstream_as_failed(task_id: str) -> int:
    """Sync version: Mark all tasks that depend on this task_id as upstream failed."""
    with db.sync_session() as session:
        result = session.execute(
            mark_downstream_stmt(TaskStatus.UPSTREAM_FAILED),
            {'upstream_tid': task_id},
        )
        logger.info(f'Marked {result.rowcount} downstream tasks as UPSTREAM_FAILED')
        return result.rowcount


def sync_mark_downstream_as_not_ready(task_id: str) -> int:
    """Sync version: Mark all tasks that depend on this task_id as NOT_READY.

    Used when the upstream download found the video isn't ready yet (premiere/scheduled live).
    Unlike UPSTREAM_FAILED, NOT_READY signals a temporary condition that will be retried.
    """
    with db.sync_session() as session:
        result = session.execute(
            mark_downstream_stmt(
                TaskStatus.NOT_READY,
                'Upstream video not ready for download yet',
                extra_excluded=(TaskStatus.NOT_READY,),
            ),
            {'upstream_tid': task_id},
        )
        logger.info(f'Marked {result.rowcount} downstream tasks as NOT_READY')
        return result.rowcount


def sync_mark_downstream_as_skipped(task_id: str) -> int:
    """Sync version: Mark all tasks that depend on this task_id as SKIPPED.

    Used when the upstream download was skipped because the owner is at their
    storage limit. Like NOT_READY, this is a temporary condition — the next
    subscription cycle re-evaluates the media once space is freed.
    """
    with db.sync_session() as session:
        result = session.execute(
            mark_downstream_stmt(
                TaskStatus.SKIPPED,
                'Upstream download skipped (storage limit reached)',
                extra_excluded=(TaskStatus.SKIPPED,),
            ),
            {'upstream_tid': task_id},
        )
        logger.info(f'Marked {result.rowcount} downstream tasks as SKIPPED')
        return result.rowcount


def sync_skip_downstream_transcripts(task_id: str, message: str) -> int:
    """Terminate the transcript chained after a download that finished without downloading.

    Scoped to TRANSCRIPT_GENERATION because the sibling sprite row is dispatched by
    DownloadHooks.on_success, which runs *after* the job body — an unfiltered sweep
    would mark it SKIPPED microseconds before that dispatch.

    Returns:
        Number of rows marked (0 when the download had no transcript)
    """
    with db.sync_session() as session:
        result = session.execute(
            mark_downstream_stmt(
                TaskStatus.SKIPPED,
                message,
                extra_excluded=(TaskStatus.SKIPPED,),
                task_types=(TaskType.TRANSCRIPT_GENERATION,),
            ),
            {'upstream_tid': task_id},
        )
        return result.rowcount


def sync_find_active_by_url_and_type(
    url: str,
    media_type: str | None,
    task_type: TaskType,
    active_statuses: list[TaskStatus],
) -> TaskRecord | None:
    """Find an active task matching URL, media_type, and task_type.

    Used to detect duplicate tasks before creating new ones.

    Args:
        url: The download job URL
        media_type: The media type value (e.g., 'AUDIO', 'VIDEO') or None
        task_type: The type of task (DOWNLOAD, TRANSCRIPT_GENERATION, etc.)
        active_statuses: List of statuses considered "active" (e.g., QUEUED, IN_PROGRESS)

    Returns:
        TaskRecord if an active task exists, None otherwise
    """
    return sync_find_one(
        {
            'task_type': task_type,
            'download_job_url': url,
            'media_type': media_type,
            'status': active_statuses,
        }
    )


def sync_find_latest_not_ready_task(url: str, media_type: str | None) -> TaskRecord | None:
    """Find the most recent non-deleted NOT_READY download task for a URL.

    Used to upsert the visible placeholder for unreleased videos instead of
    inserting a duplicate on every subscription run.

    Args:
        url: The download job URL
        media_type: The media type value (e.g., 'AUDIO', 'VIDEO') or None

    Returns:
        The newest matching TaskRecord, or None
    """
    with db.sync_session() as session:
        conditions = [
            TaskRecord.task_type == TaskType.DOWNLOAD,
            TaskRecord.download_job_url == url,
            TaskRecord.media_type == media_type,
            TaskRecord.status == TaskStatus.NOT_READY,
            TaskRecord.deleted_at.is_(None),
        ]
        stmt = select(TaskRecord).where(and_(*conditions)).order_by(TaskRecord.id.desc())
        result = session.execute(stmt)
        return result.scalars().first()


def sync_soft_delete_not_ready_tasks(url: str, media_type: str | None) -> int:
    """Soft-delete lingering NOT_READY tasks (any task type) for a URL.

    Called when a real download chain is persisted for the URL, so stale
    placeholders don't clutter the tasks table. Soft delete keeps FK
    references from media_details intact.

    Args:
        url: The download job URL
        media_type: The media type value (e.g., 'AUDIO', 'VIDEO') or None

    Returns:
        Number of rows soft-deleted
    """
    with db.sync_session() as session:
        conditions = [
            TaskRecord.download_job_url == url,
            TaskRecord.media_type == media_type,
            TaskRecord.status == TaskStatus.NOT_READY,
            TaskRecord.deleted_at.is_(None),
        ]
        stmt = (
            update(TaskRecord)
            .where(and_(*conditions))
            .values(deleted_at=utc_now(), updated_at=utc_now())
        )
        result = session.execute(stmt)
        return result.rowcount


def sync_release_cancelled_task_slot(url: str, media_type: str | None, task_type: TaskType) -> int:
    """Free the ix_task_records_active_unique slot held by a CANCELLED row.

    That partial index counts CANCELLED as active, so a cancelled row blocks every
    later insert for the same (task_type, url, media_type). Setting deleted_at is
    not enough — the index predicate has no deleted_at clause — so the status must
    move out of the predicate too.

    Only for task types where a cancel applies to that run rather than to the URL:
    a cancelled *download* must keep blocking, or the next subscription tick
    resurrects work the user dismissed.

    Returns:
        Number of rows retired
    """
    with db.sync_session() as session:
        conditions = [
            TaskRecord.task_type == task_type,
            TaskRecord.download_job_url == url,
            TaskRecord.media_type == media_type,
            TaskRecord.status == TaskStatus.CANCELLED,
        ]
        stmt = (
            update(TaskRecord)
            .where(and_(*conditions))
            .values(status=TaskStatus.DELETED, deleted_at=utc_now(), updated_at=utc_now())
        )
        result = session.execute(stmt)
        return result.rowcount


def sync_retire_placeholder(
    task_id: str | None,
    status: TaskStatus,
    message: str,
    *,
    soft_delete: bool = False,
    fields: dict | None = None,
) -> bool:
    """Move a RESOLVING placeholder off RESOLVING, if it is still RESOLVING.

    The status guard is what makes this callable from every populate exit path plus the
    catch-all in run_populate_media_details: whichever runs first records the specific
    reason, and the rest become no-ops. It also keeps a user's cancel intact — a
    CANCELLED placeholder is not RESOLVING, so nothing overwrites it.

    soft_delete additionally hides the row, for the cases where another row (an existing
    NOT_READY placeholder, the expanded playlist's children) is the real feedback. Note
    the status change is what frees the ix_task_records_active_unique slot; deleted_at
    is not in that index's predicate.

    Returns:
        True if this call retired the row.
    """
    if not task_id:
        return False
    with db.sync_session() as session:
        values = {
            'status': status,
            'status_message': message,
            'pending_payload': None,
            'updated_at': utc_now(),
            **(fields or {}),
        }
        if soft_delete:
            values['deleted_at'] = utc_now()
        stmt = (
            update(TaskRecord)
            .where(
                and_(
                    TaskRecord.task_id == task_id,
                    TaskRecord.status == TaskStatus.RESOLVING,
                )
            )
            .values(**values)
        )
        return session.execute(stmt).rowcount > 0


def sync_adopt_placeholder(task_id: str, updated_fields: dict) -> int | None:
    """Turn a RESOLVING placeholder into the chain's real download row.

    Conditional on the row still being RESOLVING so a cancel that landed during the
    metadata fetch wins: the caller reads the None as "stand down", which is the whole
    cooperative-cancel mechanism (revoke_task can't reach the populate job, since the
    placeholder task_id is deliberately never a JobSpec.task_id).

    Returns:
        The row's primary key, or None if it was no longer RESOLVING.
    """
    with db.sync_session() as session:
        stmt = (
            update(TaskRecord)
            .where(
                and_(
                    TaskRecord.task_id == task_id,
                    TaskRecord.status == TaskStatus.RESOLVING,
                )
            )
            .values(pending_payload=None, updated_at=utc_now(), **updated_fields)
            .returning(TaskRecord.id)
        )
        return session.execute(stmt).scalar_one_or_none()


def sync_get_next_queue_sequence() -> int:
    """Next value from the task_queue_sequence Postgres sequence.

    One monotonic series shared by every dispatch path so the UI can order
    tasks by (priority, queue_sequence).
    """
    with db.sync_session() as session:
        return session.scalar(select(TASK_QUEUE_SEQUENCE.next_value()))
