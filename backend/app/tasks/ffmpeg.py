"""Shared ffmpeg subprocess execution for job bodies (clips, sprites)."""

import os
import signal
import subprocess
import time
from collections.abc import Callable

from orchestrator import JobCancelled

FFMPEG_POLL_INTERVAL_SECONDS = 0.5


def kill_process_group(proc: subprocess.Popen) -> None:
    """Kill an ffmpeg process and anything it spawned (start_new_session=True)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def run_ffmpeg_cancellable(
    cmd: list[str],
    timeout: float,
    cancel_event=None,
    on_tick: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess:
    """Run ffmpeg, killable mid-encode via the job's cancel event.

    The encode runs in its own process group, so cancellation kills exactly
    that group and nothing else.

    Args:
        cmd: FFmpeg command argv
        timeout: Seconds before the process is killed and TimeoutExpired raised
        cancel_event: threading.Event; when set, the process group is killed
        on_tick: Called once per poll interval while ffmpeg runs. Lets a caller
            report liveness for pipelines ffmpeg cannot report progress on (the
            sprite `tile` filter emits nothing until EOF).
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=FFMPEG_POLL_INTERVAL_SECONDS)
                return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired as e:
                if cancel_event is not None and cancel_event.is_set():
                    msg = 'FFmpeg cancelled'
                    raise JobCancelled(msg) from e
                if time.monotonic() > deadline:
                    raise subprocess.TimeoutExpired(cmd, timeout) from e
                if on_tick is not None:
                    on_tick()
    except BaseException:
        # Covers the deadline and cancel exits above, but also an on_tick that
        # throws (it writes to the DB) — without this, ffmpeg outlives the job
        # that started it and keeps burning a core until it finishes on its own.
        if proc.poll() is None:
            kill_process_group(proc)
            proc.wait()
        raise
