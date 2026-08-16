"""Subprocess runner: spawned child jobs, progress forwarding, SIGTERM, crashes.

These spawn real child processes (a few seconds each).
"""

import asyncio
import os
import threading
from types import SimpleNamespace

import pytest

from orchestrator.context import ChildJobError, JobCancelled
from orchestrator.subprocess_runner import run_child_job
from tests.orchestrator.helpers import wait_for


def _handle():
    return SimpleNamespace(cancel_event=threading.Event(), child_process=None, shutdown=False)


def test_child_runs_job_and_forwards_progress():
    events = []
    result = run_child_job(
        'diag_echo', [{'x': 1}], 'task-echo', _handle(), progress_callback=events.append
    )
    assert result['echo'] == {'x': 1}
    assert result['pid'] != os.getpid(), 'must run in a separate process'
    assert any(
        e.get('task_id') == 'task-echo' and e.get('percent_complete') == 50 for e in events
    ), f'progress event not forwarded: {events}'


def test_child_failure_raises_with_traceback():
    with pytest.raises(ChildJobError) as excinfo:
        run_child_job(
            'diag_fail',
            ['unique-failure-message'],
            'task-fail',
            _handle(),
            progress_callback=lambda m: None,
        )
    assert 'unique-failure-message' in str(excinfo.value)
    assert excinfo.value.child_traceback
    assert 'RuntimeError' in excinfo.value.child_traceback


def test_unknown_child_job_raises():
    with pytest.raises(ChildJobError):
        run_child_job(
            'no-such-job', [], 'task-unknown', _handle(), progress_callback=lambda m: None
        )


async def test_sigterm_cancels_sleeping_child():
    handle = _handle()
    runner = asyncio.create_task(
        asyncio.to_thread(
            run_child_job,
            'diag_sleep',
            [30.0],
            'task-sleep',
            handle,
            lambda m: None,
            2.0,  # term_grace
        )
    )

    assert await wait_for(lambda: handle.child_process is not None, timeout=15.0), (
        'child never started'
    )
    handle.cancel_event.set()

    with pytest.raises(JobCancelled):
        await asyncio.wait_for(runner, timeout=20.0)
