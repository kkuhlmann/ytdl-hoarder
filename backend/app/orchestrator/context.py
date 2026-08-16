"""Execution context and control-flow exceptions for orchestrator job bodies.

JobContext carries a job's identity, its persisted attempt counter, a
cancellation event, and the "skip the rest of the pipeline" flag.
"""

import threading
from typing import NoReturn


class SkipJob(Exception):  # noqa: N818 — control-flow signal, not an error condition
    """The body already wrote its own terminal status; run no further hooks.

    Raised by the quota-skip, superseded-media, and cancel-during-sleep paths,
    which all set their own TaskRecord state before raising.
    """


class JobCancelled(Exception):  # noqa: N818 — control-flow signal, not an error condition
    """The job was cancelled (cancel event set / ML child SIGTERM'd).

    The wrapper responds by running hooks.on_cancel (partial-output cleanup)
    instead of on_success/on_failure.
    """


class RetryJob(Exception):  # noqa: N818 — control-flow signal, not an error condition
    """The body requests an automatic retry (scheduled via next_retry_at)."""

    def __init__(self, exc: BaseException | None = None):
        self.exc = exc
        super().__init__(str(exc) if exc else 'retry requested')


class ChildJobError(Exception):
    """A subprocess (ML child) job failed; carries the child's traceback text."""

    def __init__(self, message: str, child_traceback: str | None = None):
        self.child_traceback = child_traceback
        super().__init__(message)


class JobContext:
    """Everything a job body may touch about its own execution."""

    def __init__(
        self,
        task_id: str,
        attempt: int = 0,
        cancel_event: threading.Event | None = None,
        user_id: int | None = None,
    ):
        self.task_id = task_id
        # Number of automatic retries so far (0 on the first run, 1 on the
        # first retry, ...). Loaded from TaskRecord.retry_count for tracked jobs.
        self.attempt = attempt
        self.cancel_event = cancel_event if cancel_event is not None else threading.Event()
        self.user_id = user_id
        # Set by the body to suppress the downstream job on early-return paths.
        self.skip_downstream = False

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        """Cooperative cancellation point: raise if this job has been cancelled."""
        if self.cancel_event.is_set():
            msg = f'Job {self.task_id} cancelled'
            raise JobCancelled(msg)

    def retry(self, exc: BaseException | None = None) -> NoReturn:
        raise RetryJob(exc)
