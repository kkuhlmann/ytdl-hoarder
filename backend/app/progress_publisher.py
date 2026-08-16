"""In-process progress broadcaster for real-time SSE updates.

Job bodies run inside the uvicorn process (lane threads) or a spawned ML
child, so progress events fan out through an in-memory broadcaster:

- Lane threads publish via loop.call_soon_threadsafe.
- The ML child publishes into a multiprocessing queue (configure_child); the
  parent's subprocess runner forwards each message with forward_raw_event.
- SSE clients subscribe and receive ready-parsed message dicts
  ({'event_type', 'task_id', ...}).
"""

import asyncio
import threading
from typing import Any

from logger import logger

# Per-subscriber buffer. A subscriber that falls this far behind starts losing
# the oldest events (progress is fire-and-forget; clients reconcile via REST).
SUBSCRIBER_QUEUE_MAX = 512


class ProgressBroadcaster:
    """Fan-out of progress events to SSE subscribers (single-process)."""

    # When set (ML child process mode), events are enqueued to the parent
    # instead of being fanned out locally. See configure_child().
    _child_queue = None

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attach the event loop that owns the subscribers (lifespan startup)."""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        """Register an SSE client. Must be called on the event loop."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def publish(self, event_type: str, task_id: str, data: dict[str, Any]) -> bool:
        """Publish an event. Safe from the event loop, lane threads, and the child."""
        message = {
            'event_type': event_type,
            'task_id': task_id,
            **data,
        }

        if ProgressBroadcaster._child_queue is not None:
            # ML child process: hand the event to the parent, which forwards it.
            try:
                ProgressBroadcaster._child_queue.put(('progress_event', message))
            except Exception as e:  # noqa: BLE001 — progress is best-effort; a dead pipe must not fail the job
                logger.warning(f'Failed to enqueue progress event to parent: {e}')
                return False
            else:
                return True

        loop = self._loop
        if loop is None or loop.is_closed():
            # No SSE possible (startup, tests, shutdown) — fire-and-forget drop.
            return False

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is loop:
            self._fanout(message)
        else:
            loop.call_soon_threadsafe(self._fanout, message)
        return True

    def _fanout(self, message: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Slow subscriber: drop its oldest event to make room.
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


broadcaster = ProgressBroadcaster()


def configure_child(queue) -> None:
    """Route all publish_* calls into a multiprocessing queue (ML child mode).

    Called once at ML-child bootstrap; the orchestrator's subprocess runner
    drains the queue in the parent and re-publishes via forward_raw_event().
    """
    ProgressBroadcaster._child_queue = queue  # noqa: SLF001 — same module as the class


def forward_raw_event(message: dict) -> bool:
    """Re-publish a fully-formed event message received from an ML child."""
    payload = dict(message)
    event_type = payload.pop('event_type', 'progress')
    task_id = payload.pop('task_id', '')
    return broadcaster.publish(event_type, task_id, payload)


def publish_progress(task_id: str, data: dict[str, Any], user_id: int | None = None) -> bool:
    """
    Args:
        data: Progress data (percent_complete, eta_seconds, download_phase, status_message)
        user_id: Optional user_id for server-side SSE filtering

    Returns:
        True if published successfully, False otherwise
    """
    if user_id is not None:
        data = {**data, 'user_id': user_id}
    return broadcaster.publish('progress', task_id, data)


def publish_status_change(
    task_id: str,
    status: str,
    message: str = '',
    user_id: int | None = None,
    fields: dict[str, Any] | None = None,
) -> bool:
    """
    Publish a status change event (e.g., QUEUED, IN_PROGRESS, COMPLETE, FAILED).

    Args:
        user_id: Optional user_id for server-side SSE filtering
        fields: Extra TaskRecord values to carry alongside the status, for state a
            client cannot derive and would otherwise only see after a refetch. Keep to
            self-contained scalars — anything the server computes across rows (queue
            position, downstream links) still needs the REST list.

    Returns:
        True if published successfully, False otherwise
    """
    event_data: dict[str, Any] = {'status': status, 'status_message': message, **(fields or {})}
    if user_id is not None:
        event_data['user_id'] = user_id
    return broadcaster.publish('status_change', task_id, event_data)
