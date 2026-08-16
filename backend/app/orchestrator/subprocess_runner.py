"""Parent-side runner for ML jobs in spawned child processes.

Transcription runs in a fresh `spawn` child so faster-whisper/ctranslate2 load
only there and their memory is reclaimed when the child exits. The parent:

- starts the child with a multiprocessing Queue for messages,
- forwards the child's progress events to the SSE publisher,
- terminates the child (SIGTERM, then SIGKILL after a grace period) when the
  job's cancel event is set,
- raises JobCancelled / ChildJobError so the job wrapper can run the right hooks.

This function blocks and is intended to run inside a lane worker thread.
"""

import multiprocessing
import queue as queue_mod
import time

from logger import logger
from progress_publisher import forward_raw_event

from .context import ChildJobError, JobCancelled

TERM_GRACE_SECONDS = 10
_NO_RESULT = object()


def run_child_job(  # noqa: C901 — a message loop over the child protocol; one branch per message kind
    child_job: str,
    args: list,
    task_id: str,
    handle,
    progress_callback=forward_raw_event,
    term_grace: float = TERM_GRACE_SECONDS,
):
    from . import child_main

    ctx = multiprocessing.get_context('spawn')
    messages = ctx.Queue()
    process = ctx.Process(
        target=child_main.child_entry,
        args=(child_job, list(args), task_id, messages),
        name=f'ml-{child_job}-{task_id[:8]}',
    )
    process.start()
    handle.child_process = process
    logger.info(f'Started ML child pid={process.pid} for job {child_job} (task {task_id})')

    result = _NO_RESULT
    error: dict | None = None
    kill_deadline: float | None = None

    try:
        while True:
            if handle.cancel_event.is_set() and process.is_alive():
                if kill_deadline is None:
                    logger.info(f'Terminating ML child pid={process.pid} (task {task_id})')
                    process.terminate()
                    kill_deadline = time.monotonic() + term_grace
                elif time.monotonic() > kill_deadline:
                    logger.warning(f'ML child pid={process.pid} ignored SIGTERM; killing')
                    process.kill()
                    kill_deadline = time.monotonic() + term_grace

            try:
                kind, payload = messages.get(timeout=0.25)
            except queue_mod.Empty:
                if not process.is_alive():
                    break
                continue

            if kind == 'progress_event':
                try:
                    progress_callback(payload)
                except Exception as e:  # noqa: BLE001 — a bad progress event must not abort draining the child
                    logger.warning(f'Failed to forward child progress event: {e}')
            elif kind == 'result':
                result = payload
            elif kind == 'error':
                error = payload

        process.join()

        # Final drain — the child may have exited right after its last put().
        while True:
            try:
                kind, payload = messages.get_nowait()
            except queue_mod.Empty:
                break
            if kind == 'progress_event':
                try:
                    progress_callback(payload)
                except Exception as e:  # noqa: BLE001 — a bad progress event must not abort draining the child
                    logger.warning(f'Failed to forward child progress event: {e}')
            elif kind == 'result':
                result = payload
            elif kind == 'error':
                error = payload
    finally:
        handle.child_process = None
        messages.close()

    if handle.cancel_event.is_set():
        msg = f'ML child job {task_id} cancelled'
        raise JobCancelled(msg)
    if error is not None:
        raise ChildJobError(error.get('message', 'ML child job failed'), error.get('traceback'))
    if process.exitcode != 0:
        msg = f'ML child exited with code {process.exitcode}'
        raise ChildJobError(msg)
    if result is _NO_RESULT:
        msg = 'ML child exited without sending a result'
        raise ChildJobError(msg)
    return result
