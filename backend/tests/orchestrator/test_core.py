"""Orchestrator core: lanes, ordering, prioritize, cancel, status registry."""

import threading
import time

import pytest

from models import TaskStatus
from orchestrator.core import OrchestratorNotRunningError, map_task_status_to_state
from orchestrator.jobs import (
    ALL_LANES,
    DEFAULT_LANE,
    DOWNLOADS_LANE,
    SUBSCRIPTIONS_LANE,
    JobDefinition,
    JobSpec,
    register_job,
)
from tests.orchestrator.helpers import wait_for


def _register_blocking_job(name, lane, started, release, log=None):
    """A body that records its start, then waits for release (or cancel)."""

    def body(ctx, label=None):
        started.append(label or ctx.task_id)
        while not release.is_set() and not ctx.cancel_event.is_set():
            time.sleep(0.005)
        if log is not None:
            log.append(label or ctx.task_id)
        return label

    register_job(JobDefinition(name=name, fn=body, lane=lane))
    return body


async def test_default_lane_runs_two_concurrently(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('blocker', DEFAULT_LANE, started, release)

    for i in range(3):
        await orch_instance.submit(JobSpec(job_name='blocker', args=(f'job{i}',), tracked=False))

    assert await wait_for(lambda: len(started) == 2)
    # Third job stays queued while both slots are busy
    snapshot = orch_instance.runtime_snapshot()
    assert len(snapshot['lanes'][DEFAULT_LANE]['queued']) == 1
    assert len(started) == 2

    release.set()
    assert await wait_for(lambda: len(started) == 3)


async def test_downloads_lane_is_serial(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('dl', DOWNLOADS_LANE, started, release)

    for i in range(2):
        await orch_instance.submit(JobSpec(job_name='dl', args=(f'dl{i}',), tracked=False))

    assert await wait_for(lambda: len(started) == 1)
    await wait_for(lambda: len(started) > 1, timeout=0.3)
    assert len(started) == 1, 'second download must wait for the first'

    release.set()
    assert await wait_for(lambda: len(started) == 2)


async def test_subscriptions_lane_is_serial(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('sub', SUBSCRIPTIONS_LANE, started, release)

    for i in range(2):
        await orch_instance.submit(JobSpec(job_name='sub', args=(f'sub{i}',), tracked=False))

    assert await wait_for(lambda: len(started) == 1)
    await wait_for(lambda: len(started) > 1, timeout=0.3)
    assert len(started) == 1, 'second subscription pipeline must wait for the first'

    release.set()
    assert await wait_for(lambda: len(started) == 2)


async def test_subscription_work_does_not_occupy_default_lane_slots(orch_instance):
    """Both cron pipelines running must still leave the default lane free."""
    sub_started, sub_release = [], threading.Event()
    _register_blocking_job('sub_pipeline', SUBSCRIPTIONS_LANE, sub_started, sub_release)
    fast_done = []
    register_job(
        JobDefinition(name='fast', fn=lambda ctx, label: fast_done.append(label), lane=DEFAULT_LANE)
    )

    for i in range(2):
        await orch_instance.submit(
            JobSpec(job_name='sub_pipeline', args=(f'sub{i}',), tracked=False)
        )
    assert await wait_for(lambda: len(sub_started) == 1)

    await orch_instance.submit(JobSpec(job_name='fast', args=('manual',), tracked=False))

    assert await wait_for(lambda: fast_done == ['manual']), (
        'default-lane work must not wait on the subscription lane'
    )
    assert len(sub_started) == 1, 'subscription pipeline still holding its slot'
    sub_release.set()


async def test_high_priority_job_jumps_a_saturated_default_lane(orch_instance):
    """The regression: a manual download must not queue behind a subscription backlog."""
    started = []
    # One event per saturating job so exactly one slot can be freed. Releasing both
    # at once dispatches two jobs concurrently, and since bodies run in the thread
    # pool their appends race — the lane would still pop by priority, but `started`
    # would not record it.
    holds = {'busy0': threading.Event(), 'busy1': threading.Event()}

    def hold_body(ctx, label=None):
        started.append(label)
        while not holds[label].is_set() and not ctx.cancel_event.is_set():
            time.sleep(0.005)
        return label

    def record_body(ctx, label=None):
        started.append(label)
        return label

    register_job(JobDefinition(name='hold', fn=hold_body, lane=DEFAULT_LANE))
    register_job(JobDefinition(name='work', fn=record_body, lane=DEFAULT_LANE))

    # Saturate both slots.
    for label in holds:
        await orch_instance.submit(JobSpec(job_name='hold', args=(label,), tracked=False))
    assert await wait_for(lambda: len(started) == 2)

    # A backlog of subscription-priority jobs, then one manual-priority job last.
    for i in range(20):
        await orch_instance.submit(
            JobSpec(job_name='work', args=(f'backlog{i}',), tracked=False, priority=5)
        )
    await orch_instance.submit(
        JobSpec(job_name='work', args=('manual',), tracked=False, priority=1)
    )

    # Free one slot; 'busy1' holds the other, so the 21 queued jobs drain through it
    # one at a time and `started` records the lane's pop order exactly.
    holds['busy0'].set()
    assert await wait_for(lambda: len(started) == 23)
    assert started[2] == 'manual', f'priority-1 job must run first, got {started[2]}'
    holds['busy1'].set()


def test_lane_set_matches_all_lanes(orch_instance):
    assert set(orch_instance.runtime_snapshot()['lanes']) == set(ALL_LANES)


async def test_queued_count_reports_waiting_jobs(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('counted', DOWNLOADS_LANE, started, release)

    for i in range(3):
        await orch_instance.submit(JobSpec(job_name='counted', args=(f'j{i}',), tracked=False))
    assert await wait_for(lambda: len(started) == 1)

    assert orch_instance.queued_count(DOWNLOADS_LANE) == 2, 'running job must not be counted'
    assert orch_instance.queued_count(DEFAULT_LANE) == 0
    assert orch_instance.queued_count('nonexistent') == 0

    release.set()


async def test_pop_order_priority_then_sequence(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('ordered', DOWNLOADS_LANE, started, release)

    # Occupy the single slot so the rest queue up.
    await orch_instance.submit(
        JobSpec(job_name='ordered', args=('first',), tracked=False, queue_sequence=1)
    )
    assert await wait_for(lambda: len(started) == 1)

    await orch_instance.submit(
        JobSpec(job_name='ordered', args=('p5s30',), tracked=False, priority=5, queue_sequence=30)
    )
    await orch_instance.submit(
        JobSpec(job_name='ordered', args=('p1s20',), tracked=False, priority=1, queue_sequence=20)
    )
    await orch_instance.submit(
        JobSpec(job_name='ordered', args=('p5s10',), tracked=False, priority=5, queue_sequence=10)
    )

    release.set()
    assert await wait_for(lambda: len(started) == 4)
    assert started == ['first', 'p1s20', 'p5s10', 'p5s30']


async def test_prioritize_moves_job_to_front_without_changing_task_id(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('prio', DOWNLOADS_LANE, started, release)

    await orch_instance.submit(
        JobSpec(job_name='prio', args=('running',), tracked=False, queue_sequence=1)
    )
    assert await wait_for(lambda: len(started) == 1)

    await orch_instance.submit(
        JobSpec(job_name='prio', args=('a',), tracked=False, priority=5, queue_sequence=10)
    )
    last_id = await orch_instance.submit(
        JobSpec(
            job_name='prio',
            args=('winner',),
            task_id='prioritize-me',
            tracked=False,
            priority=5,
            queue_sequence=20,
        )
    )
    assert last_id == 'prioritize-me'
    assert await orch_instance.prioritize('prioritize-me') is True

    release.set()
    assert await wait_for(lambda: len(started) == 3)
    assert started == ['running', 'winner', 'a']

    # Prioritizing an unknown/running task returns False
    assert await orch_instance.prioritize('nope') is False


async def test_cancel_queued_job_dequeues(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('cq', DOWNLOADS_LANE, started, release)

    await orch_instance.submit(JobSpec(job_name='cq', args=('running',), tracked=False))
    assert await wait_for(lambda: len(started) == 1)
    await orch_instance.submit(
        JobSpec(job_name='cq', args=('queued',), task_id='queued-job', tracked=False)
    )

    assert await orch_instance.cancel('queued-job') == 'dequeued'
    assert await orch_instance.get_status('queued-job') == 'REVOKED'

    release.set()
    await wait_for(lambda: len(started) == 2, timeout=0.5)
    assert started == ['running'], 'cancelled job must never start'


async def test_cancel_running_job_signals_cancel_event(orch_instance):
    started = []

    def body(ctx):
        started.append(ctx.task_id)
        ctx.cancel_event.wait(5)
        ctx.check_cancelled()
        return 'finished'

    register_job(JobDefinition(name='cr', fn=body, lane=DOWNLOADS_LANE))
    await orch_instance.submit(JobSpec(job_name='cr', task_id='running-job', tracked=False))
    assert await wait_for(lambda: len(started) == 1)

    assert await orch_instance.cancel('running-job') == 'signalled'
    assert await wait_for(lambda: orch_instance._results['running-job'].state == 'REVOKED')

    # Unknown id → 'unknown' (treated as already finished by callers)
    assert await orch_instance.cancel('never-heard-of-it') == 'unknown'


async def test_submit_from_thread(orch_instance):
    import asyncio

    done = []

    def body(ctx, label):
        done.append(label)
        return label

    register_job(JobDefinition(name='threaded', fn=body, lane=DEFAULT_LANE))

    def from_thread():
        return orch_instance.submit_from_thread(
            JobSpec(job_name='threaded', args=('via-thread',), tracked=False)
        )

    task_id = await asyncio.to_thread(from_thread)
    assert task_id
    assert await wait_for(lambda: done == ['via-thread'])
    assert await orch_instance.get_status(task_id) == 'SUCCESS'


async def test_downstream_receives_upstream_retval(orch_instance):
    received = []

    def parent(ctx):
        return {'answer': 41}

    def child(ctx, payload):
        received.append(payload)
        return payload

    register_job(JobDefinition(name='parent', fn=parent, lane=DEFAULT_LANE))
    register_job(JobDefinition(name='child', fn=child, lane=DEFAULT_LANE))

    await orch_instance.submit(
        JobSpec(
            job_name='parent',
            tracked=False,
            downstream=JobSpec(job_name='child', task_id='child-id', tracked=False),
        )
    )
    assert await wait_for(lambda: received == [{'answer': 41}])
    assert await orch_instance.get_status('child-id') == 'SUCCESS'


async def test_skip_downstream_suppresses_child(orch_instance):
    received = []

    def parent(ctx):
        ctx.skip_downstream = True
        return {'answer': 42}

    def child(ctx, payload):
        received.append(payload)

    register_job(JobDefinition(name='parent-skip', fn=parent, lane=DEFAULT_LANE))
    register_job(JobDefinition(name='child-skip', fn=child, lane=DEFAULT_LANE))

    await orch_instance.submit(
        JobSpec(
            job_name='parent-skip',
            task_id='parent-id',
            tracked=False,
            downstream=JobSpec(job_name='child-skip', task_id='child-skip-id', tracked=False),
        )
    )
    assert await wait_for(
        lambda: (
            orch_instance._results.get('parent-id') is not None
            and orch_instance._results['parent-id'].state == 'SUCCESS'
        )
    )
    await wait_for(lambda: bool(received), timeout=0.3)
    assert received == []
    # Downstream never submitted → unknown to the registry
    assert 'child-skip-id' not in orch_instance._results


async def test_submit_when_not_running_raises(job_registry):
    from orchestrator.core import Orchestrator

    register_job(JobDefinition(name='noop', fn=lambda ctx: None, lane=DEFAULT_LANE))
    o = Orchestrator()
    with pytest.raises(OrchestratorNotRunningError):
        await o.submit(JobSpec(job_name='noop', tracked=False))
    with pytest.raises(OrchestratorNotRunningError):
        o.submit_from_thread(JobSpec(job_name='noop', tracked=False))


async def test_duplicate_task_id_submission_is_ignored(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('dup', DOWNLOADS_LANE, started, release)

    await orch_instance.submit(
        JobSpec(job_name='dup', args=('one',), task_id='same-id', tracked=False)
    )
    await orch_instance.submit(
        JobSpec(job_name='dup', args=('two',), task_id='same-id', tracked=False)
    )
    release.set()
    assert await wait_for(lambda: len(started) == 1)
    await wait_for(lambda: len(started) == 2, timeout=0.3)
    assert started == ['one']


async def test_result_registry_ttl_sweep(orch_instance):
    def body(ctx):
        return 'ok'

    register_job(JobDefinition(name='quick', fn=body, lane=DEFAULT_LANE))
    task_id = await orch_instance.submit(JobSpec(job_name='quick', tracked=False))
    assert await wait_for(
        lambda: (
            task_id in orch_instance._results and orch_instance._results[task_id].state == 'SUCCESS'
        )
    )

    # Age the entry past the TTL and trigger a sweep
    orch_instance._results[task_id].updated -= 3601
    orch_instance._sweep_results()
    assert task_id not in orch_instance._results


def test_job_state_mapping_table():
    expected = {
        TaskStatus.NONE: 'PENDING',
        TaskStatus.QUEUED: 'PENDING',
        TaskStatus.IN_PROGRESS: 'STARTED',
        TaskStatus.POSTPROCESSING: 'STARTED',
        TaskStatus.COMPLETE: 'SUCCESS',
        TaskStatus.RETRY: 'RETRY',
        TaskStatus.FAILED: 'FAILURE',
        TaskStatus.UPSTREAM_FAILED: 'FAILURE',
        TaskStatus.CANCELLED: 'REVOKED',
        TaskStatus.SKIPPED: 'REVOKED',
        TaskStatus.DELETED: 'REVOKED',
        TaskStatus.NOT_READY: 'PENDING',
    }
    for status, state in expected.items():
        assert map_task_status_to_state(status) == state


async def test_get_status_falls_back_to_task_record(orch_instance, test_database):
    from models import TaskRecord, TaskType
    from repositories import task_records as tr_repo

    tr_repo.sync_insert_task(
        TaskRecord(
            task_id='db-only-task',
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.COMPLETE,
        )
    )
    assert await orch_instance.get_status('db-only-task') == 'SUCCESS'
    assert await orch_instance.get_status('completely-unknown') == 'PENDING'
