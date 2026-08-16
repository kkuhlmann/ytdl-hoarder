"""Retry policies: exponential backoff with full jitter.

- base_delay=B, max_delay=M → the delay before the n-th retry is
  min(B * 2**(n-1), M).
- With jitter enabled (the default), the *actual* delay is a random value in
  [0, computed] — full jitter, which spreads out retry storms.
- max_retries=N → the body may retry N times; the (N+1)-th failure is final.

The transient-DB retry is an in-thread sleep-and-retry decorator for
orchestration bodies that open sync DB sessions.
"""

import random
import time
from dataclasses import dataclass
from functools import wraps

from sqlalchemy.exc import InterfaceError, OperationalError

from logger import logger

# Transient connection-level failures worth retrying (Docker DNS EAI_AGAIN,
# dropped connections, DB briefly unreachable). Deliberately NOT DBAPIError —
# IntegrityError/ProgrammingError indicate real bugs and must not be retried.
TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError)


@dataclass(frozen=True)
class RetryPolicy:
    base_delay: float
    max_delay: float
    max_retries: int
    jitter: bool = True

    def backoff(self, attempt: int) -> float:
        """Un-jittered delay before retry `attempt` (1-indexed)."""
        return min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)

    def compute_delay(self, attempt: int) -> float:
        """Actual delay before retry `attempt`, with full jitter."""
        delay = self.backoff(attempt)
        if self.jitter:
            return random.uniform(0, delay)  # noqa: S311 — retry jitter, not a secret
        return delay


# Downloads: patient — YouTube rate limits can last hours.
DOWNLOAD_RETRY_POLICY = RetryPolicy(base_delay=300, max_delay=60 * 60 * 8, max_retries=20)
# Transcription: transient failures (ffmpeg, model load) resolve quickly.
TRANSCRIPT_RETRY_POLICY = RetryPolicy(base_delay=30, max_delay=30 * 60, max_retries=5)
# Clips: quick, user-interactive jobs.
CLIP_RETRY_POLICY = RetryPolicy(base_delay=30, max_delay=5 * 60, max_retries=3)
# Transient DB connection blips (Docker DNS): retry fast, give up fast.
DB_RETRY_POLICY = RetryPolicy(base_delay=2, max_delay=60, max_retries=5)

# The policies above are wired to jobs by *name* in tasks.registry; this maps them by
# TaskType instead, so a task row can be served with its own attempt ceiling ("3 of 20"
# in the Tasks UI) without the reader knowing which job produced it. SPRITE_GENERATION
# is absent because sprites have no retry policy at all.
TASK_TYPE_RETRY_POLICIES: dict[str, RetryPolicy] = {
    'DOWNLOAD': DOWNLOAD_RETRY_POLICY,
    'TRANSCRIPT_GENERATION': TRANSCRIPT_RETRY_POLICY,
    'CLIP_GENERATION': CLIP_RETRY_POLICY,
}


def max_retries_for_task_type(task_type) -> int | None:
    """Attempt ceiling for a task type, or None when it is never retried."""
    key = getattr(task_type, 'value', task_type)
    policy = TASK_TYPE_RETRY_POLICIES.get(key)
    return policy.max_retries if policy else None


def retry_transient_db(fn):
    """Retry a sync function in-place on transient DB connection errors.

    For orchestration bodies that open sync DB sessions: sleep with a 2s→60s
    jittered backoff and call again, up to 5 tries.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        attempt = 0
        while True:
            try:
                return fn(*args, **kwargs)
            except TRANSIENT_DB_ERRORS as e:
                attempt += 1
                if attempt > DB_RETRY_POLICY.max_retries:
                    raise
                delay = DB_RETRY_POLICY.compute_delay(attempt)
                logger.warning(
                    f'{fn.__name__}: transient DB error (attempt {attempt}/'
                    f'{DB_RETRY_POLICY.max_retries}), retrying in {delay:.1f}s: {e}'
                )
                time.sleep(delay)

    return wrapper
