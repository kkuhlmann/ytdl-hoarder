"""Statement builders shared by the async and sync task_records modules."""

from sqlalchemy import and_, not_, text, update

from models import TaskRecord, TaskStatus, TaskType, utc_now

# Terminal statuses a downstream-marking sweep must never overwrite.
_DOWNSTREAM_BASE_EXCLUDED = (
    TaskStatus.COMPLETE,
    TaskStatus.FAILED,
    TaskStatus.UPSTREAM_FAILED,
    TaskStatus.CANCELLED,
)


def mark_downstream_stmt(
    target_status: TaskStatus,
    status_message: str | None = None,
    extra_excluded: tuple[TaskStatus, ...] = (),
    task_types: tuple[TaskType, ...] = (),
):
    """UPDATE every task whose upstream_task_ids contains :upstream_tid.

    Bind 'upstream_tid' at execution time — the name avoids colliding with the
    task_id column inside the jsonb containment test.

    task_types narrows the sweep to those types. Callers that terminate a whole
    chain want the default (every downstream row); the exception is a path that
    ends one sibling while another is still due to be dispatched.
    """
    values: dict = {'status': target_status, 'updated_at': utc_now()}
    if status_message is not None:
        values['status_message'] = status_message
    conditions = [
        text('task_records.upstream_task_ids::jsonb ? :upstream_tid'),
        not_(TaskRecord.status.in_([*_DOWNSTREAM_BASE_EXCLUDED, *extra_excluded])),
    ]
    if task_types:
        conditions.append(TaskRecord.task_type.in_(task_types))
    return update(TaskRecord).where(and_(*conditions)).values(**values)
