"""
Server-Sent Events (SSE) endpoint for real-time task progress updates.

Subscribes to the in-process progress broadcaster and streams events to
connected clients, filtered per user.
"""

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Query, Request

from dependencies import get_required_user_id
from logger import logger
from progress_publisher import broadcaster

router = APIRouter()

KEEPALIVE_INTERVAL = 30  # seconds


async def progress_event_generator(
    task_ids: list[str] | None = None,
    all_tasks: bool = True,
    user_id: int | None = None,
    is_admin: bool = False,
) -> AsyncGenerator[str]:
    """
    Async generator that yields SSE-formatted progress events.

    Args:
        task_ids: Optional list of task IDs to filter events (if all_tasks is False)
        all_tasks: If True, stream all task events; if False, filter by task_ids
        user_id: If provided (and not admin), only stream events for this user
        is_admin: If True, bypass user_id filtering (admin sees all events)
    """
    queue = broadcaster.subscribe()
    logger.debug('SSE client subscribed to progress broadcaster')

    task_id_set = set(task_ids) if task_ids and not all_tasks else None

    try:
        while True:
            try:
                parsed = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
            except TimeoutError:
                # Send keepalive comment to prevent connection timeout
                yield ': keepalive\n\n'
                continue

            if task_id_set and parsed.get('task_id') not in task_id_set:
                continue

            # Fails closed: an event with no user_id is dropped rather than
            # broadcast, so a publisher that forgets to attribute one leaks
            # nothing. Admins still see everything.
            if user_id and not is_admin and parsed.get('user_id') != user_id:
                continue

            yield f'data: {json.dumps(parsed)}\n\n'

    except asyncio.CancelledError:
        logger.debug('SSE client disconnected')
        raise
    finally:
        broadcaster.unsubscribe(queue)
        logger.debug('SSE cleanup complete')


@router.get('/progress')
async def stream_progress(
    request: Request,
    task_ids: str | None = Query(
        default=None,
        description='Comma-separated list of task IDs to filter events',
    ),
    all_tasks: bool = Query(
        default=True,
        description='If true, stream all task events; if false, filter by task_ids',
    ),
    user_id: int = Depends(get_required_user_id),
):
    """
    SSE endpoint for real-time task progress updates.

    Connect to this endpoint to receive progress events as Server-Sent Events.
    Events are filtered by user_id for non-admin users.
    """
    from fastapi.responses import StreamingResponse

    parsed_task_ids = task_ids.split(',') if task_ids else None
    is_admin = getattr(request.state, 'is_admin', False)

    return StreamingResponse(
        progress_event_generator(
            task_ids=parsed_task_ids,
            all_tasks=all_tasks,
            user_id=user_id,
            is_admin=is_admin,
        ),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
        },
    )
