"""Job wrapper: lifecycle handling (hooks order, retry scheduling, guards)."""

import threading
from datetime import timedelta
from types import SimpleNamespace

from models import TaskRecord, TaskStatus, TaskType, utc_now
from orchestrator import wrapper
from orchestrator.context import JobCancelled, SkipJob
from orchestrator.hooks import DownloadHooks, NullHooks
from orchestrator.jobs import JobDefinition, JobSpec
from orchestrator.retry import RetryPolicy
from repositories import task_records as tr_repo


class RecordingHooks(NullHooks):
    """Capture the hook call order; instances are shared via a class list."""

    calls: list

    def __init__(self):
        type(self).calls = []

    def before_start(self, task_id, args, kwargs):
        type(self).calls.append('before_start')

    def on_success(self, retval, task_id, args, kwargs):
        type(self).calls.append('on_success')

    def on_failure(self, exc, task_id, args, kwargs, einfo=None):
        type(self).calls.append('on_failure')

    def on_retry(self, exc, task_id, args, kwargs, einfo=None):
        type(self).calls.append('on_retry')

    def on_cancel(self, task_id, args):
        type(self).calls.append('on_cancel')


def _handle(shutdown=False):
    return SimpleNamespace(cancel_event=threading.Event(), child_process=None, shutdown=shutdown)


def _make_record(task_id, status=TaskStatus.QUEUED, retry_count=0):
    record = TaskRecord(
        task_id=task_id,
        task_type=TaskType.DOWNLOAD,
        status=status,
        retry_count=retry_count,
    )
    return tr_repo.sync_insert_task(record)


def _run(body, task_id, policy=None, tracked=True, handle=None, args=()):
    definition = JobDefinition(
        name='test-job', fn=body, hooks_factory=RecordingHooks, retry_policy=policy
    )
    spec = JobSpec(job_name='test-job', args=args, task_id=task_id, tracked=tracked)
    return wrapper.run_job_sync(definition, spec, handle or _handle())


def test_success_runs_before_start_then_on_success(test_database):
    _make_record('w-success')
    outcome = _run(lambda ctx: {'id': 7}, 'w-success')
    assert outcome.kind == wrapper.SUCCESS
    assert outcome.retval == {'id': 7}
    assert outcome.skip_downstream is False
    assert RecordingHooks.calls == ['before_start', 'on_success']


def test_skipjob_runs_no_further_hooks(test_database):
    _make_record('w-skip')

    def body(ctx):
        raise SkipJob

    outcome = _run(body, 'w-skip')
    assert outcome.kind == wrapper.SKIPPED
    assert RecordingHooks.calls == ['before_start']


def test_cancel_runs_on_cancel(test_database):
    _make_record('w-cancel')

    def body(ctx):
        msg = 'user cancelled'
        raise JobCancelled(msg)

    outcome = _run(body, 'w-cancel')
    assert outcome.kind == wrapper.CANCELLED
    assert RecordingHooks.calls == ['before_start', 'on_cancel']


def test_shutdown_cancel_leaves_state_for_recovery(test_database):
    _make_record('w-shutdown', status=TaskStatus.IN_PROGRESS)

    def body(ctx):
        msg = 'shutting down'
        raise JobCancelled(msg)

    outcome = _run(body, 'w-shutdown', handle=_handle(shutdown=True))
    assert outcome.kind == wrapper.SHUTDOWN
    assert RecordingHooks.calls == ['before_start'], 'no status writes on shutdown'
    record = tr_repo.sync_get_task_by_task_id('w-shutdown')
    assert record.status == TaskStatus.IN_PROGRESS


def test_retryjob_schedules_next_retry(test_database):
    policy = RetryPolicy(base_delay=300, max_delay=8 * 3600, max_retries=20, jitter=False)
    _make_record('w-retry')

    def body(ctx):
        ctx.retry(ValueError('rate limited'))

    before = utc_now()
    outcome = _run(body, 'w-retry', policy=policy)
    assert outcome.kind == wrapper.RETRY
    assert RecordingHooks.calls == ['before_start', 'on_retry']

    record = tr_repo.sync_get_task_by_task_id('w-retry')
    assert record.retry_count == 1
    assert record.next_retry_at is not None
    # jitter=False → exactly base_delay (300s) after "now", give or take test time
    assert (
        before + timedelta(seconds=295)
        <= record.next_retry_at
        <= utc_now() + timedelta(seconds=305)
    )


def test_retry_preserves_task_id_and_attempt_grows(test_database):
    policy = RetryPolicy(base_delay=10, max_delay=100, max_retries=20, jitter=False)
    _make_record('w-retry2', retry_count=3)
    seen_attempts = []

    def body(ctx):
        seen_attempts.append(ctx.attempt)
        ctx.retry(ValueError('again'))

    outcome = _run(body, 'w-retry2', policy=policy)
    assert outcome.kind == wrapper.RETRY
    assert seen_attempts == [3], 'ctx.attempt reflects the persisted retry_count'
    record = tr_repo.sync_get_task_by_task_id('w-retry2')
    assert record.retry_count == 4
    assert record.task_id == 'w-retry2', 'automatic retries preserve the task_id'


def test_retry_exhaustion_becomes_failure(test_database):
    policy = RetryPolicy(base_delay=10, max_delay=100, max_retries=5, jitter=False)
    _make_record('w-exhausted', retry_count=5)

    def body(ctx):
        ctx.retry(ValueError('still broken'))

    outcome = _run(body, 'w-exhausted', policy=policy)
    assert outcome.kind == wrapper.FAILURE
    assert RecordingHooks.calls == ['before_start', 'on_failure']


def test_plain_exception_fails_without_policy(test_database):
    _make_record('w-boom')

    def body(ctx):
        msg = 'boom'
        raise ValueError(msg)

    outcome = _run(body, 'w-boom')
    assert outcome.kind == wrapper.FAILURE
    assert isinstance(outcome.error, ValueError)
    assert RecordingHooks.calls == ['before_start', 'on_failure']


def test_cancelled_record_wins_over_late_success(test_database):
    _make_record('w-late', status=TaskStatus.CANCELLED)
    outcome = _run(lambda ctx: {'id': 1}, 'w-late')
    assert outcome.kind == wrapper.CANCELLED
    assert RecordingHooks.calls == ['before_start', 'on_cancel']
    record = tr_repo.sync_get_task_by_task_id('w-late')
    assert record.status == TaskStatus.CANCELLED, 'CANCELLED must never be overwritten'


def test_not_ready_retval_skips_downstream(test_database):
    _make_record('w-notready')
    outcome = _run(lambda ctx: {'status': TaskStatus.NOT_READY.value}, 'w-notready')
    assert outcome.kind == wrapper.SUCCESS
    assert outcome.skip_downstream is True


def test_ctx_skip_downstream_flag(test_database):
    _make_record('w-skipflag')

    def body(ctx):
        ctx.skip_downstream = True
        return {'id': 2}

    outcome = _run(body, 'w-skipflag')
    assert outcome.kind == wrapper.SUCCESS
    assert outcome.skip_downstream is True


def test_untracked_retry_becomes_failure(test_database):
    def body(ctx):
        ctx.retry(ValueError('nowhere to persist'))

    outcome = _run(body, 'w-untracked', tracked=False)
    assert outcome.kind == wrapper.FAILURE


# --- DownloadHooks-specific guards (ported from tasks/base.py) ---


def test_download_hooks_not_ready_guard(test_database):
    _make_record('dh-notready', status=TaskStatus.NOT_READY)
    hooks = DownloadHooks()
    hooks.on_success({'status': TaskStatus.NOT_READY.value}, 'dh-notready', [{}], {})
    record = tr_repo.sync_get_task_by_task_id('dh-notready')
    assert record.status == TaskStatus.NOT_READY, 'NOT_READY must be preserved'


def test_download_hooks_invalid_retval_marks_failed(test_database):
    _make_record('dh-invalid', status=TaskStatus.IN_PROGRESS)
    hooks = DownloadHooks()
    hooks.on_success(None, 'dh-invalid', [{}], {})
    record = tr_repo.sync_get_task_by_task_id('dh-invalid')
    assert record.status == TaskStatus.FAILED


def test_download_hooks_failure_marks_downstream(test_database):
    _make_record('dh-up', status=TaskStatus.IN_PROGRESS)
    downstream = TaskRecord(
        task_id='dh-down',
        task_type=TaskType.TRANSCRIPT_GENERATION,
        status=TaskStatus.QUEUED,
        upstream_task_ids=['dh-up'],
    )
    tr_repo.sync_insert_task(downstream)

    hooks = DownloadHooks()
    hooks.on_failure(ValueError('dead'), 'dh-up', [{}], {})

    assert tr_repo.sync_get_task_by_task_id('dh-up').status == TaskStatus.FAILED
    assert tr_repo.sync_get_task_by_task_id('dh-down').status == TaskStatus.UPSTREAM_FAILED


# --- Terminal-status guarantee: a broken hook must not strand the record ---


class ExplodingHooks(NullHooks):
    """Every status-writing hook raises, as a hook whose DB write fails does."""

    def before_start(self, task_id, args, kwargs):
        msg = 'before_start exploded'
        raise RuntimeError(msg)

    def on_success(self, retval, task_id, args, kwargs):
        msg = 'on_success exploded'
        raise RuntimeError(msg)

    def on_failure(self, exc, task_id, args, kwargs, einfo=None):
        msg = 'on_failure exploded'
        raise RuntimeError(msg)

    def on_retry(self, exc, task_id, args, kwargs, einfo=None):
        msg = 'on_retry exploded'
        raise RuntimeError(msg)

    def on_cancel(self, task_id, args):
        msg = 'on_cancel exploded'
        raise RuntimeError(msg)


def _run_exploding(body, task_id, policy=None, status=TaskStatus.IN_PROGRESS):
    _make_record(task_id, status=status)
    definition = JobDefinition(
        name='test-job', fn=body, hooks_factory=ExplodingHooks, retry_policy=policy
    )
    spec = JobSpec(job_name='test-job', args=(), task_id=task_id)
    return wrapper.run_job_sync(definition, spec, _handle())


def test_broken_success_hook_still_completes_the_record(test_database):
    outcome = _run_exploding(lambda ctx: {'id': 1}, 'x-success')
    assert outcome.kind == wrapper.SUCCESS, 'a hook is bookkeeping; it cannot change the outcome'
    record = tr_repo.sync_get_task_by_task_id('x-success')
    assert record.status == TaskStatus.COMPLETE
    assert record.percent_complete == 100


def test_broken_failure_hook_still_fails_the_record(test_database):
    def body(ctx):
        msg = 'boom'
        raise ValueError(msg)

    outcome = _run_exploding(body, 'x-failure')
    assert outcome.kind == wrapper.FAILURE
    record = tr_repo.sync_get_task_by_task_id('x-failure')
    assert record.status == TaskStatus.FAILED
    assert 'boom' in record.status_message


def test_broken_retry_hook_still_schedules_the_retry(test_database):
    policy = RetryPolicy(base_delay=10, max_delay=100, max_retries=5, jitter=False)

    def body(ctx):
        ctx.retry(ValueError('rate limited'))

    outcome = _run_exploding(body, 'x-retry', policy=policy)
    assert outcome.kind == wrapper.RETRY
    record = tr_repo.sync_get_task_by_task_id('x-retry')
    assert record.status == TaskStatus.RETRY
    # The scheduler scans RETRY rows *by* next_retry_at — a status without it parks the job.
    assert record.next_retry_at is not None
    assert record.retry_count == 1


def test_broken_cancel_hook_leaves_the_record_cancelled(test_database):
    def body(ctx):
        msg = 'user cancelled'
        raise JobCancelled(msg)

    outcome = _run_exploding(body, 'x-cancel')
    assert outcome.kind == wrapper.CANCELLED
    assert tr_repo.sync_get_task_by_task_id('x-cancel').status == TaskStatus.CANCELLED


def test_broken_before_start_hook_does_not_abort_the_job(test_database):
    outcome = _run_exploding(lambda ctx: {'id': 2}, 'x-before', status=TaskStatus.QUEUED)
    assert outcome.kind == wrapper.SUCCESS
    assert tr_repo.sync_get_task_by_task_id('x-before').status == TaskStatus.COMPLETE


def test_reconcile_never_overwrites_a_terminal_status(test_database):
    """A status the body already wrote wins — the fallback only reclaims running rows."""
    _make_record('x-notready', status=TaskStatus.IN_PROGRESS)

    def body(ctx):
        tr_repo.sync_update_one('x-notready', {'status': TaskStatus.NOT_READY})
        return {'status': TaskStatus.NOT_READY.value}

    outcome = _run(body, 'x-notready')
    assert outcome.kind == wrapper.SUCCESS
    assert tr_repo.sync_get_task_by_task_id('x-notready').status == TaskStatus.NOT_READY


def test_shutdown_outcome_is_left_for_recovery(test_database):
    """SHUTDOWN carries no patch: startup recovery owns those rows deliberately."""

    def body(ctx):
        msg = 'shutting down'
        raise JobCancelled(msg)

    _make_record('x-shutdown', status=TaskStatus.IN_PROGRESS)
    definition = JobDefinition(name='test-job', fn=body, hooks_factory=ExplodingHooks)
    spec = JobSpec(job_name='test-job', args=(), task_id='x-shutdown')
    outcome = wrapper.run_job_sync(definition, spec, _handle(shutdown=True))

    assert outcome.kind == wrapper.SHUTDOWN
    assert tr_repo.sync_get_task_by_task_id('x-shutdown').status == TaskStatus.IN_PROGRESS


def test_download_hooks_cancel_cleanup_accepts_task_url(test_database):
    """on_cancel must survive its cleanup call — every caller passes task_url=.

    A raise that escapes the wrapper leaves the row marked running while the lane
    moves on to the next download.
    """
    from services.cleanup import cleanup_task_files

    assert cleanup_task_files(task_title='Some Title', task_url='https://x/watch?v=1') == 0

    _make_record('dh-cancel', status=TaskStatus.CANCELLED)
    DownloadHooks().on_cancel('dh-cancel', [{'title': 'Some Title', 'url': 'https://x/watch?v=1'}])
