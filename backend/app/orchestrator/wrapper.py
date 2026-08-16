"""The job wrapper: lifecycle handling around a plain job body.

run_job_sync() is executed inside a lane worker thread:

    before_start → body → on_success        (normal completion)
                        → nothing           (SkipJob — body wrote its own state)
                        → on_cancel         (JobCancelled — cleanup partial output)
                        → on_retry + next_retry_at   (RetryJob within policy)
                        → on_failure        (RetryJob past policy, or any exception)

plus three guards:
- a NOT_READY retval never overwrites the body's NOT_READY status (hook-level),
- a CANCELLED TaskRecord is never overwritten by a late success/failure
  (a cancel always wins over a job that finishes anyway), and
- every outcome reconciles the TaskRecord to a terminal status, so a hook that
  raises cannot leave the row running forever (see reconcile_terminal_status).

All DB access here is sync (lane threads), matching the task bodies.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from logger import logger
from models import TaskStatus, utc_now
from repositories import task_records as tr_repo

from .context import ChildJobError, JobCancelled, JobContext, RetryJob, SkipJob
from .error_codes import classify_error
from .hooks import NullHooks, error_message
from .jobs import SUBPROCESS_RUNNER, JobDefinition, JobSpec

# Outcome kinds
SUCCESS = 'success'
SKIPPED = 'skipped'
CANCELLED = 'cancelled'
RETRY = 'retry'
FAILURE = 'failure'
SHUTDOWN = 'shutdown'  # cancelled by orchestrator stop — DB state left for recovery

# Statuses that mean "a job is still working on this row", and are therefore the
# only ones the terminal reconcile may overwrite. Everything else — including a
# body-written NOT_READY placeholder or a user's CANCELLED — already won.
_RECLAIMABLE_STATUSES = (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.POSTPROCESSING)

# Fallback status writes, mirroring what the corresponding hook would have said.
_SUCCESS_PATCH = {
    'status': TaskStatus.COMPLETE,
    'status_message': 'Completed',
    'percent_complete': 100,
}
_SKIPPED_PATCH = {'status': TaskStatus.SKIPPED, 'status_message': 'Skipped'}
_CANCELLED_PATCH = {'status': TaskStatus.CANCELLED, 'status_message': 'Cancelled'}
_NOT_READY_PATCH = {'status': TaskStatus.NOT_READY, 'status_message': 'Not released yet'}


@dataclass
class Outcome:
    kind: str
    retval: Any = None
    error: BaseException | None = None
    # True when the downstream job must not be enqueued (body set
    # ctx.skip_downstream, or it returned a NOT_READY result).
    skip_downstream: bool = False
    # Status fields the TaskRecord must end up carrying. Applied only as a
    # fallback, when the hooks did not manage to write a terminal status
    # themselves. None for SHUTDOWN — recovery deliberately owns those rows.
    terminal_patch: dict | None = None


def _load_attempt(task_id: str) -> int:
    record = tr_repo.sync_get_task_by_task_id(task_id)
    return record.retry_count if record is not None else 0


def _is_record_cancelled(task_id: str) -> bool:
    record = tr_repo.sync_get_task_by_task_id(task_id)
    return record is not None and record.status == TaskStatus.CANCELLED


def _run_hook(hook_fn, task_id: str, name: str, *args) -> None:
    """Invoke one lifecycle hook, absorbing anything it raises.

    Hooks are bookkeeping (status writes, SSE, file cleanup). A hook that throws
    — its own bug, or a DB write that fails because the disk is full — must not
    change the job's outcome, and must not abandon the TaskRecord: whatever
    status it failed to write, reconcile_terminal_status writes instead.
    """
    try:
        hook_fn(*args)
    except Exception:
        logger.exception(f'{name} hook raised for task {task_id}')


def reconcile_terminal_status(task_id: str, outcome: Outcome) -> None:
    """Force the TaskRecord to the status this outcome implies.

    Without it, a failed hook leaves the row IN_PROGRESS after its job has
    already released the lane slot — and since the UI renders IN_PROGRESS and
    POSTPROCESSING identically to a live job, the row spins forever and looks
    like a download running concurrently with the real one.

    Only _RECLAIMABLE_STATUSES are overwritten, so a terminal status a hook or
    the body did manage to write always wins.
    """
    if outcome.terminal_patch is None:
        return
    try:
        record = tr_repo.sync_get_task_by_task_id(task_id)
        if record is None or record.status not in _RECLAIMABLE_STATUSES:
            return
        tr_repo.sync_update_one(task_id, outcome.terminal_patch)
        logger.warning(
            f'Task {task_id} left its lane still marked {record.status.value}; '
            f'forced to {outcome.terminal_patch["status"].value}'
        )
    except Exception:
        logger.exception(f'Could not reconcile terminal status for task {task_id}')


def run_job_sync(definition: JobDefinition, spec: JobSpec, handle) -> Outcome:
    """Run one job to an Outcome, guaranteeing its TaskRecord ends up terminal."""
    try:
        outcome = _execute(definition, spec, handle)
    except Exception as exc:
        # _execute funnels every body exception itself, so reaching here means
        # the wrapper's own bookkeeping broke (e.g. the DB is unreachable).
        logger.exception(f'Job wrapper failed for {spec.task_id}')
        outcome = Outcome(
            FAILURE,
            error=exc,
            terminal_patch={
                'status': TaskStatus.FAILED,
                'status_message': f'Task failed: {error_message(exc)}',
            },
        )
    if spec.tracked:
        reconcile_terminal_status(spec.task_id, outcome)
    return outcome


def _execute(definition: JobDefinition, spec: JobSpec, handle) -> Outcome:
    task_id = spec.task_id
    tracked = spec.tracked
    hooks = (
        definition.hooks_factory()
        if (tracked and definition.hooks_factory is not None)
        else NullHooks()
    )
    attempt = _load_attempt(task_id) if tracked else 0
    ctx = JobContext(
        task_id,
        attempt=attempt,
        cancel_event=handle.cancel_event,
        user_id=spec.user_id,
    )
    args = list(spec.args)
    kwargs: dict = {}

    try:
        _run_hook(hooks.before_start, task_id, 'before_start', task_id, args, kwargs)
        if definition.runner == SUBPROCESS_RUNNER:
            from . import subprocess_runner

            retval = subprocess_runner.run_child_job(definition.child_job, args, task_id, handle)
        else:
            retval = definition.fn(ctx, *args)

    except SkipJob:
        # Body already wrote its terminal status (SKIPPED/CANCELLED) — do nothing.
        return Outcome(SKIPPED, terminal_patch=_SKIPPED_PATCH)

    except (JobCancelled, ChildJobError) as exc:
        cancelled = isinstance(exc, JobCancelled) or handle.cancel_event.is_set()
        if cancelled:
            if handle.shutdown:
                # Orchestrator shutdown, not a user cancel: leave TaskRecord as-is
                # (IN_PROGRESS) so startup recovery resumes it next boot.
                logger.info(f'Job {task_id} interrupted by shutdown; leaving state for recovery')
                return Outcome(SHUTDOWN)
            _run_hook(hooks.on_cancel, task_id, 'on_cancel', task_id, args)
            return Outcome(CANCELLED, error=exc, terminal_patch=_CANCELLED_PATCH)
        # ChildJobError without a cancel — a genuine child failure.
        return _handle_failure_or_retry(definition, hooks, exc, task_id, args, kwargs, attempt)

    except RetryJob as retry_exc:
        exc = retry_exc.exc or retry_exc
        return _schedule_retry(definition, hooks, exc, task_id, args, kwargs, attempt, tracked)

    except Exception as exc:  # noqa: BLE001 — the outcome funnel: any body exception becomes a FAILED task
        return _finalize_failure(hooks, exc, task_id, args, kwargs, tracked)

    # Success path — but a cancel that landed while the body was finishing wins.
    if tracked and _is_record_cancelled(task_id):
        logger.info(f'Job {task_id} finished after being cancelled; running cancel cleanup')
        _run_hook(hooks.on_cancel, task_id, 'on_cancel', task_id, args)
        return Outcome(CANCELLED, terminal_patch=_CANCELLED_PATCH)

    _run_hook(hooks.on_success, task_id, 'on_success', retval, task_id, args, kwargs)
    not_ready = isinstance(retval, dict) and retval.get('status') == TaskStatus.NOT_READY.value
    return Outcome(
        SUCCESS,
        retval=retval,
        skip_downstream=ctx.skip_downstream or not_ready,
        # An unreleased video succeeded at *deferring*, not downloading — forcing
        # COMPLETE here would mark it downloaded (mirrors DownloadHooks.on_success).
        terminal_patch=_NOT_READY_PATCH if not_ready else _SUCCESS_PATCH,
    )


def _handle_failure_or_retry(definition, hooks, exc, task_id, args, kwargs, attempt) -> Outcome:
    """A child-process failure: apply the retry policy exactly like RetryJob."""
    policy = definition.retry_policy
    if policy is not None and attempt < policy.max_retries:
        return _schedule_retry(definition, hooks, exc, task_id, args, kwargs, attempt, True)
    return _finalize_failure(hooks, exc, task_id, args, kwargs, tracked=True)


def _schedule_retry(definition, hooks, exc, task_id, args, kwargs, attempt, tracked) -> Outcome:
    policy = definition.retry_policy
    if not tracked or policy is None or attempt >= policy.max_retries:
        # Max retries exceeded (or nowhere to persist the retry) — final failure.
        return _finalize_failure(hooks, exc, task_id, args, kwargs, tracked)

    next_attempt = attempt + 1
    delay = policy.compute_delay(next_attempt)
    next_retry_at = utc_now() + timedelta(seconds=delay)
    _run_hook(hooks.on_retry, task_id, 'on_retry', exc, task_id, args, kwargs, None)
    tr_repo.sync_update_one(
        task_id,
        {
            'retry_count': next_attempt,
            'next_retry_at': next_retry_at,
        },
    )
    logger.info(
        f'Job {task_id} scheduled for retry {next_attempt}/{policy.max_retries} in {delay:.0f}s'
    )
    # next_retry_at rides along: the scheduler scans RETRY rows *by* that column,
    # so a status written without it would park the job forever.
    return Outcome(
        RETRY,
        error=exc,
        terminal_patch={
            'status': TaskStatus.RETRY,
            'status_message': f'Retrying due to: {error_message(exc)}',
            'error_code': classify_error(exc),
            'retry_count': next_attempt,
            'next_retry_at': next_retry_at,
        },
    )


def _finalize_failure(hooks, exc, task_id, args, kwargs, tracked) -> Outcome:
    # A cancel that raced the failure wins (don't overwrite CANCELLED).
    if tracked and _is_record_cancelled(task_id):
        _run_hook(hooks.on_cancel, task_id, 'on_cancel', task_id, args)
        return Outcome(CANCELLED, error=exc, terminal_patch=_CANCELLED_PATCH)
    _run_hook(hooks.on_failure, task_id, 'on_failure', exc, task_id, args, kwargs, None)
    return Outcome(
        FAILURE,
        error=exc,
        terminal_patch={
            'status': TaskStatus.FAILED,
            'status_message': f'Task failed: {error_message(exc)}',
            'error_code': classify_error(exc),
        },
    )
