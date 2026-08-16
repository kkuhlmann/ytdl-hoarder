"""Live lane resizing: grow, shrink, clamping, and the app_settings mapping."""

import threading
import time

from models import APP_SETTINGS_DEFAULTS
from orchestrator.jobs import (
    DEFAULT_LANE,
    DEFAULT_LANE_CONCURRENCY,
    JobDefinition,
    JobSpec,
    register_job,
)
from orchestrator.lanes import Lane
from repositories.settings import LANE_CONCURRENCY_COLUMNS
from tests.orchestrator.helpers import wait_for


def _register_blocking_job(name, lane, started, release):
    def body(ctx, label=None):
        started.append(label or ctx.task_id)
        while not release.is_set() and not ctx.cancel_event.is_set():
            time.sleep(0.005)
        return label

    register_job(JobDefinition(name=name, fn=body, lane=lane))


async def test_grow_starts_queued_jobs_without_waiting(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('grow', DEFAULT_LANE, started, release)

    for i in range(4):
        await orch_instance.submit(JobSpec(job_name='grow', args=(f'job{i}',), tracked=False))

    assert await wait_for(lambda: len(started) == 2)

    orch_instance.set_lane_concurrency({DEFAULT_LANE: 4})

    assert await wait_for(lambda: len(started) == 4), 'grow must not wait for running jobs'
    release.set()


async def test_shrink_leaves_running_jobs_alone_and_lands_lazily(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('shrink', DEFAULT_LANE, started, release)

    orch_instance.set_lane_concurrency({DEFAULT_LANE: 3})
    for i in range(5):
        await orch_instance.submit(JobSpec(job_name='shrink', args=(f'job{i}',), tracked=False))
    assert await wait_for(lambda: len(started) == 3)

    orch_instance.set_lane_concurrency({DEFAULT_LANE: 1})

    lane = orch_instance.runtime_snapshot()['lanes'][DEFAULT_LANE]
    assert lane['concurrency'] == 1
    assert lane['capacity'] == 3, 'a running job keeps its permit until it finishes'
    assert len(lane['running']) == 3, 'shrinking must not cancel running jobs'

    release.set()
    assert await wait_for(lambda: len(started) == 5)
    assert await wait_for(
        lambda: orch_instance.runtime_snapshot()['lanes'][DEFAULT_LANE]['capacity'] == 1
    ), 'capacity must walk down to the target as jobs finish'


async def test_shrunk_lane_only_runs_one_job_at_a_time(orch_instance):
    started, release = [], threading.Event()
    _register_blocking_job('narrow', DEFAULT_LANE, started, release)

    orch_instance.set_lane_concurrency({DEFAULT_LANE: 1})
    for i in range(3):
        await orch_instance.submit(JobSpec(job_name='narrow', args=(f'job{i}',), tracked=False))

    assert await wait_for(lambda: len(started) == 1)
    await wait_for(lambda: len(started) > 1, timeout=0.3)
    assert len(started) == 1, 'a narrowed lane must dispatch serially'

    release.set()
    assert await wait_for(lambda: len(started) == 3)


async def test_unknown_lane_name_is_ignored(orch_instance):
    orch_instance.set_lane_concurrency({'nonexistent': 4, DEFAULT_LANE: 3})
    assert orch_instance.runtime_snapshot()['lanes'][DEFAULT_LANE]['concurrency'] == 3


def test_set_concurrency_clamps_to_at_least_one():
    lane = Lane('l', 2)
    lane.set_concurrency(0)
    assert lane.concurrency == 1


def test_lane_fallbacks_match_the_app_settings_defaults():
    """The orchestrator's no-database fallback and the DB defaults must not drift."""
    assert {
        lane: APP_SETTINGS_DEFAULTS[column] for lane, column in LANE_CONCURRENCY_COLUMNS.items()
    } == DEFAULT_LANE_CONCURRENCY
