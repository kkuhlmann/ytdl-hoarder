"""Entrypoint for spawned ML child processes.

Runs in a fresh interpreter (`spawn` context). Heavy libraries (faster-whisper,
ctranslate2) are imported lazily inside the job functions, so the child only
pays for what its job actually uses — and the parent process never pays at all.

Contract with the parent (see subprocess_runner):
- progress events are routed through progress_publisher.configure_child(queue)
  as ('progress_event', message) tuples;
- exactly one ('result', retval) or ('error', {...}) is sent before exit;
- SIGTERM raises JobCancelled inside the job, giving cleanup code a chance to
  run; the parent escalates to SIGKILL after a grace period.
"""

import contextlib
import os
import signal
import time
import traceback

from .context import JobCancelled, JobContext


def _sigterm_handler(_signum, _frame):
    msg = 'ML child received SIGTERM'
    raise JobCancelled(msg)


# --- Child job functions -----------------------------------------------------
# Each takes (task_id, *args) and returns a JSON-serializable result.


def _run_transcription(task_id: str, md: dict):
    """Whisper transcription + embeddings for one MediaDetails payload."""
    from tasks.transcription import run_transcript_job

    ctx = JobContext(task_id)
    return run_transcript_job(ctx, md)


def _diag_echo(task_id: str, payload=None):
    """Diagnostic job: publish one progress event and echo the payload."""
    from progress_publisher import publish_progress

    publish_progress(task_id, {'percent_complete': 50, 'status_message': 'echoing'})
    return {'echo': payload, 'pid': os.getpid()}


def _diag_sleep(_task_id: str, seconds: float = 30.0):
    """Diagnostic job: sleep in small increments (SIGTERM-interruptible)."""
    deadline = time.monotonic() + float(seconds)
    while time.monotonic() < deadline:
        time.sleep(0.05)
    return {'slept': seconds}


def _diag_fail(_task_id: str, message: str = 'diagnostic failure'):
    raise RuntimeError(message)


CHILD_JOBS = {
    'transcription': _run_transcription,
    'diag_echo': _diag_echo,
    'diag_sleep': _diag_sleep,
    'diag_fail': _diag_fail,
}


def child_entry(child_job: str, args: list, task_id: str, messages) -> None:
    """Child process main: bootstrap, run the job, report the outcome."""
    signal.signal(signal.SIGTERM, _sigterm_handler)

    import progress_publisher

    progress_publisher.configure_child(messages)

    from database import db

    db.initialize_database()

    try:
        fn = CHILD_JOBS[child_job]
        retval = fn(task_id, *args)
        messages.put(('result', retval))
    except JobCancelled:
        # The parent decides the outcome from its own cancel_event; just make
        # sure nothing half-sent lingers and exit with the conventional
        # SIGTERM status.
        messages.put(('error', {'message': 'cancelled', 'cancelled': True}))
        _flush_and_exit(messages, 143)
    except BaseException as e:  # noqa: BLE001 — child must always report, then exit
        messages.put(
            ('error', {'message': f'{type(e).__name__}: {e}', 'traceback': traceback.format_exc()})
        )
        _flush_and_exit(messages, 1)
    _flush_and_exit(messages, 0)


def _flush_and_exit(messages, code: int) -> None:
    # Give the queue's feeder thread a moment to flush buffered messages to the
    # pipe before the process dies, then exit without running atexit handlers
    # (DB teardown in a dying child is pointless and can hang).
    with contextlib.suppress(Exception):
        messages.close()
        messages.join_thread()
    os._exit(code)
