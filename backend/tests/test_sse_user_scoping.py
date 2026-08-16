"""SSE events must not cross user boundaries.

The stream fails closed: an event carrying no user_id is dropped for non-admin
subscribers rather than broadcast to everyone. Any publisher that forgets to
attribute an event therefore leaks nothing — it just goes unseen.
"""

import asyncio
import json

import pytest

from orchestrator.hooks import ClipHooks
from routers import sse


async def _collect(gen, count):
    """Pull `count` data events, ignoring keepalives."""
    out = []
    while len(out) < count:
        chunk = await asyncio.wait_for(gen.__anext__(), timeout=2)
        if chunk.startswith('data: '):
            out.append(json.loads(chunk.removeprefix('data: ').strip()))
    return out


@pytest.fixture
def publish(monkeypatch):
    """Drive progress_event_generator off a queue we control."""
    queue: asyncio.Queue = asyncio.Queue()
    monkeypatch.setattr(sse.broadcaster, 'subscribe', lambda: queue)
    monkeypatch.setattr(sse.broadcaster, 'unsubscribe', lambda q: None)
    return queue.put_nowait


async def test_other_users_events_are_not_delivered(publish):
    gen = sse.progress_event_generator(user_id=7)

    publish({'event_type': 'status_change', 'task_id': 'a', 'user_id': 99})
    publish({'event_type': 'status_change', 'task_id': 'b', 'user_id': 7})

    assert [e['task_id'] for e in await _collect(gen, 1)] == ['b']
    await gen.aclose()


async def test_unattributed_events_are_dropped_for_non_admins(publish):
    """Non-admins must not receive events from other users."""
    gen = sse.progress_event_generator(user_id=7)

    publish({'event_type': 'status_change', 'task_id': 'orphan'})
    publish({'event_type': 'status_change', 'task_id': 'mine', 'user_id': 7})

    assert [e['task_id'] for e in await _collect(gen, 1)] == ['mine']
    await gen.aclose()


async def test_admin_sees_everything(publish):
    gen = sse.progress_event_generator(user_id=7, is_admin=True)

    publish({'event_type': 'status_change', 'task_id': 'orphan'})
    publish({'event_type': 'status_change', 'task_id': 'other', 'user_id': 99})
    publish({'event_type': 'status_change', 'task_id': 'mine', 'user_id': 7})

    assert [e['task_id'] for e in await _collect(gen, 3)] == ['orphan', 'other', 'mine']
    await gen.aclose()


async def test_anonymous_stream_is_unfiltered(publish):
    """user_id=None means no filtering — the route requires auth to reach here."""
    gen = sse.progress_event_generator(user_id=None)

    publish({'event_type': 'status_change', 'task_id': 'x', 'user_id': 99})

    assert [e['task_id'] for e in await _collect(gen, 1)] == ['x']
    await gen.aclose()


async def test_task_id_filter_still_applies(publish):
    gen = sse.progress_event_generator(task_ids=['keep'], all_tasks=False, user_id=7)

    publish({'event_type': 'progress', 'task_id': 'drop', 'user_id': 7})
    publish({'event_type': 'progress', 'task_id': 'keep', 'user_id': 7})

    assert [e['task_id'] for e in await _collect(gen, 1)] == ['keep']
    await gen.aclose()


def test_clip_hooks_attribute_events_to_the_clip_owner(monkeypatch):
    """ClipHooks omitted user_id on all four transitions, so every logged-in user
    received every other user's clip task IDs — including the failure message,
    which carries ffmpeg output naming the source file (channel + title).
    """
    published = []
    monkeypatch.setattr(
        'orchestrator.hooks.publish_status_change',
        lambda task_id, status, msg='', user_id=None: published.append((status, user_id)),
    )
    monkeypatch.setattr('orchestrator.hooks.tr_repo.sync_update_one', lambda *a, **k: None)
    monkeypatch.setattr('orchestrator.hooks.clips_repo.sync_update_clip', lambda *a, **k: None)

    args = ({'clip_id': 5, 'user_id': 42},)
    hooks = ClipHooks()

    hooks.before_start('t', args, {})
    hooks.on_success(None, 't', args, {})
    hooks.on_failure(RuntimeError('ffmpeg: /mnt/audio/Channel/Title.mp3'), 't', args, {})
    hooks.on_retry(RuntimeError('boom'), 't', args, {})

    assert [user_id for _, user_id in published] == [42, 42, 42, 42]
