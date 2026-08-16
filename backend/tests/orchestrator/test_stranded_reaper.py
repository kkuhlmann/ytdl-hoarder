"""The stranded-row sweep: failing rows whose job already left its lane.

A hook whose DB write fails leaves the TaskRecord marked running after the
orchestrator has released the lane slot. The row then renders exactly like a
live download, so several of them look like concurrent downloads.
"""

from datetime import timedelta

from database import db
from models import TaskRecord, TaskStatus, TaskType, utc_now
from orchestrator.recovery import STRANDED_GRACE_SECONDS, reap_stranded_records
from repositories import task_records as tr_repo


def _insert_task(
    task_id: str,
    status: TaskStatus,
    *,
    age_seconds: float = STRANDED_GRACE_SECONDS * 2,
    task_type: TaskType = TaskType.DOWNLOAD,
    upstream_task_ids: list[str] | None = None,
) -> None:
    """Insert a TaskRecord with an explicit updated_at age."""
    session = db.get_sync_session()
    try:
        stamp = utc_now() - timedelta(seconds=age_seconds)
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type=task_type,
                status=status,
                title=f'Stranded {task_id}',
                percent_complete=14,
                upstream_task_ids=upstream_task_ids,
                created_at=stamp,
                updated_at=stamp,
            )
        )
        session.commit()
    finally:
        session.close()


def _status(task_id: str) -> TaskStatus:
    return tr_repo.sync_get_task_by_task_id(task_id).status


def test_reaps_row_with_no_orchestrator_handle(test_database):
    _insert_task('reap-stranded', TaskStatus.IN_PROGRESS)

    assert reap_stranded_records(set()) == 1
    assert _status('reap-stranded') == TaskStatus.FAILED


def test_reaps_postprocessing_rows_too(test_database):
    _insert_task('reap-postprocessing', TaskStatus.POSTPROCESSING)

    assert reap_stranded_records(set()) == 1
    assert _status('reap-postprocessing') == TaskStatus.FAILED


def test_leaves_running_job_alone(test_database):
    """The handle set is the liveness truth — a held id is never reaped."""
    _insert_task('reap-live', TaskStatus.IN_PROGRESS)

    assert reap_stranded_records({'reap-live'}) == 0
    assert _status('reap-live') == TaskStatus.IN_PROGRESS


def test_leaves_row_inside_grace_window(test_database):
    _insert_task('reap-fresh', TaskStatus.IN_PROGRESS, age_seconds=5)

    assert reap_stranded_records(set()) == 0
    assert _status('reap-fresh') == TaskStatus.IN_PROGRESS


def test_ignores_rows_that_are_not_running(test_database):
    _insert_task('reap-queued', TaskStatus.QUEUED)
    _insert_task('reap-not-ready', TaskStatus.NOT_READY)
    _insert_task('reap-retry', TaskStatus.RETRY)

    assert reap_stranded_records(set()) == 0
    assert _status('reap-queued') == TaskStatus.QUEUED
    assert _status('reap-not-ready') == TaskStatus.NOT_READY
    assert _status('reap-retry') == TaskStatus.RETRY


def test_marks_downstream_as_upstream_failed(test_database):
    _insert_task('reap-upstream', TaskStatus.IN_PROGRESS)
    _insert_task(
        'reap-downstream',
        TaskStatus.QUEUED,
        task_type=TaskType.TRANSCRIPT_GENERATION,
        upstream_task_ids=['reap-upstream'],
    )

    reap_stranded_records(set())

    assert _status('reap-upstream') == TaskStatus.FAILED
    assert _status('reap-downstream') == TaskStatus.UPSTREAM_FAILED
