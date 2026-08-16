"""Shared helpers for orchestrator tests."""

import asyncio
import time


# ASYNC109 is suppressed below: the deadline is this polling helper's API,
# not an ambient timeout the caller should impose with a cancel scope.
async def wait_for(condition, timeout: float = 5.0, interval: float = 0.01) -> bool:  # noqa: ASYNC109
    """Poll `condition()` until true or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(interval)
    return condition()
