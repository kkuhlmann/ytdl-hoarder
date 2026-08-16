"""Tests for tracked sprite-sheet generation."""

import os
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch

import pytest

import repositories.task_records as tr_repo
from database import db
from models import MediaDetails, MediaType, TaskRecord, TaskStatus, TaskType, User
from orchestrator import JobCancelled, JobContext, SkipJob
from tasks.ffmpeg import run_ffmpeg_cancellable
from tasks.sprites import (
    _build_ffmpeg_sprites_command,
    _create_elapsed_reporter,
    _format_elapsed,
    delete_partial_sprite_output,
    run_sprites_job,
    sync_submit_sprites_job,
)

SPRITE_TASK_ID = 'sprite-task-1'
MEDIA_URL = 'https://example.com/watch?v=long'


@pytest.fixture
def video_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, 'video.mp4')
        with open(path, 'wb') as f:
            f.write(b'not really a video')
        yield path


@pytest.fixture
def owner(clean_database):
    """TaskRecord.user_id is a real FK, so the submission tests need a real user."""
    session = db.get_sync_session()
    try:
        user = User(username='sprite-owner', password_hash='x', is_admin=True, is_approved=True)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id
    finally:
        session.close()


@pytest.fixture
def media(owner, video_file):
    session = db.get_sync_session()
    try:
        row = MediaDetails(
            url=MEDIA_URL,
            media_type=MediaType.VIDEO,
            title='Long Video',
            channel='Test Channel',
            file_path=video_file,
            duration=1800.0,
            owner_id=owner,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    finally:
        session.close()


@pytest.fixture
def sprite_task(clean_database, media):
    session = db.get_sync_session()
    try:
        task = TaskRecord(
            task_id=SPRITE_TASK_ID,
            task_type=TaskType.SPRITE_GENERATION,
            status=TaskStatus.IN_PROGRESS,
            status_message='Generating sprite sheet...',
            download_job_url=MEDIA_URL,
            media_type=MediaType.VIDEO,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task
    finally:
        session.close()


# --------------------------------------------------------------- elapsed reporting


@pytest.mark.parametrize(
    ('seconds', 'expected'),
    [(0, '0s'), (9.9, '9s'), (59, '59s'), (60, '1m00s'), (134, '2m14s'), (3600, '1h00m')],
)
def test_format_elapsed(seconds, expected):
    assert _format_elapsed(seconds) == expected


def test_elapsed_reporter_writes_message_and_publishes(sprite_task):
    with (
        patch('tasks.sprites.publish_progress') as mock_publish,
        patch('tasks.sprites.SPRITES_ELAPSED_UPDATE_SECONDS', 0),
    ):
        report = _create_elapsed_reporter(SPRITE_TASK_ID, user_id=7)
        report()

    task = tr_repo.sync_get_task_by_task_id(SPRITE_TASK_ID)
    assert task.status_message.startswith('Generating sprite sheet... ')
    mock_publish.assert_called_once()
    assert mock_publish.call_args.kwargs['user_id'] == 7


def test_elapsed_reporter_throttles_writes(sprite_task):
    """The tick fires twice a second; unthrottled that is ~1800 writes per run."""
    with patch('tasks.sprites.publish_progress') as mock_publish:
        report = _create_elapsed_reporter(SPRITE_TASK_ID, user_id=None)
        for _ in range(20):
            report()

    assert mock_publish.call_count == 0


# ------------------------------------------------------------------- job body guards


def _ctx():
    return JobContext(task_id=SPRITE_TASK_ID, cancel_event=threading.Event())


def test_missing_media_raises(clean_database):
    with pytest.raises(ValueError, match='not found'):
        run_sprites_job(_ctx(), {'media_details_id': 9999})


def test_missing_file_raises(clean_database, media):
    os.remove(media.file_path)
    with pytest.raises(ValueError, match='Media file not found'):
        run_sprites_job(_ctx(), {'media_details_id': media.id})


def test_missing_duration_raises(clean_database, media):
    tr_repo.sync_update_one  # noqa: B018 — keep import used symmetrical with repo helpers
    from repositories import media_details as md_repo

    md_repo.sync_update_one(media.id, {'duration': None})
    with pytest.raises(ValueError, match='no duration'):
        run_sprites_job(_ctx(), {'media_details_id': media.id})


def test_existing_sheet_skips_and_marks_row(sprite_task, media):
    base = os.path.splitext(media.file_path)[0]
    for suffix in ('.sprites.jpg', '.sprites.json'):
        with open(base + suffix, 'w') as f:
            f.write('x')

    with patch('tasks.sprites.publish_status_change'), pytest.raises(SkipJob):
        run_sprites_job(_ctx(), {'media_details_id': media.id})

    task = tr_repo.sync_get_task_by_task_id(SPRITE_TASK_ID)
    assert task.status == TaskStatus.SKIPPED
    assert task.status_message == 'Sprite sheet already exists'


def test_force_regenerates_over_existing_sheet(sprite_task, media):
    base = os.path.splitext(media.file_path)[0]
    for suffix in ('.sprites.jpg', '.sprites.json'):
        with open(base + suffix, 'w') as f:
            f.write('x')

    with patch('tasks.sprites.run_ffmpeg_cancellable') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess([], 0, '', '')
        result = run_sprites_job(_ctx(), {'media_details_id': media.id, 'force': True})

    mock_run.assert_called_once()
    assert result['media_details_id'] == media.id


def test_ffmpeg_failure_raises(sprite_task, media):
    with (
        patch('tasks.sprites.run_ffmpeg_cancellable') as mock_run,
        pytest.raises(RuntimeError, match='return code 1'),
    ):
        mock_run.return_value = subprocess.CompletedProcess([], 1, '', 'boom')
        run_sprites_job(_ctx(), {'media_details_id': media.id})


def test_ffmpeg_timeout_raises_runtime_error(sprite_task, media):
    with (
        patch('tasks.sprites.run_ffmpeg_cancellable') as mock_run,
        pytest.raises(RuntimeError, match='timed out'),
    ):
        mock_run.side_effect = subprocess.TimeoutExpired([], 900)
        run_sprites_job(_ctx(), {'media_details_id': media.id})


def test_ffmpeg_command_shape_is_unchanged():
    """Pins the byte-identical-output promise: this command must not drift."""
    cmd = _build_ffmpeg_sprites_command('in.mp4', 'out.jpg', 10, 10, 18)
    assert cmd == [
        'ffmpeg',
        '-y',
        '-i',
        'in.mp4',
        '-vf',
        'fps=1/10,scale=160:90:force_original_aspect_ratio=decrease,'
        'pad=160:90:(ow-iw)/2:(oh-ih)/2,tile=10x18',
        '-frames:v',
        '1',
        '-qscale:v',
        '5',
        'out.jpg',
    ]


# --------------------------------------------------------------------- cleanup


def test_delete_partial_output_removes_orphan_sheet(clean_database, media):
    base = os.path.splitext(media.file_path)[0]
    sprite_path = base + '.sprites.jpg'
    with open(sprite_path, 'w') as f:
        f.write('truncated')

    delete_partial_sprite_output(media.id)

    assert not os.path.exists(sprite_path)


def test_delete_partial_output_keeps_complete_sheet(clean_database, media):
    base = os.path.splitext(media.file_path)[0]
    sprite_path, metadata_path = base + '.sprites.jpg', base + '.sprites.json'
    for path in (sprite_path, metadata_path):
        with open(path, 'w') as f:
            f.write('x')

    delete_partial_sprite_output(media.id)

    assert os.path.exists(sprite_path)


# ------------------------------------------------------------- cancellable ffmpeg


def test_run_ffmpeg_cancellable_kills_on_cancel():
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(JobCancelled):
        run_ffmpeg_cancellable(['sleep', '30'], timeout=30, cancel_event=cancel_event)


def test_run_ffmpeg_cancellable_times_out():
    with pytest.raises(subprocess.TimeoutExpired):
        run_ffmpeg_cancellable(['sleep', '30'], timeout=0.6)


def test_run_ffmpeg_cancellable_fires_on_tick():
    ticks = []
    run_ffmpeg_cancellable(['sleep', '1.6'], timeout=30, on_tick=lambda: ticks.append(time.time()))
    assert len(ticks) >= 2


def test_a_throwing_on_tick_does_not_orphan_ffmpeg(monkeypatch):
    """on_tick writes to the DB; a blip there must not leak a running process."""
    spawned = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr('tasks.ffmpeg.subprocess.Popen', recording_popen)

    def explode():
        msg = 'db down'
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match='db down'):
        run_ffmpeg_cancellable(['sleep', '30'], timeout=30, on_tick=explode)

    assert spawned
    assert spawned[0].poll() is not None, 'ffmpeg was left running'


# ------------------------------------------------------------------ submission


@pytest.fixture
def submittable():
    """Neutralise the bits sync_submit_sprites_job needs a running orchestrator for."""
    with (
        patch('orchestrator.orch.submit_from_thread'),
        patch('tasks.sprites.publish_status_change'),
    ):
        yield


def test_submit_is_idempotent_while_active(clean_database, media, submittable):
    first = sync_submit_sprites_job(media, user_id=media.owner_id)
    second = sync_submit_sprites_job(media, user_id=media.owner_id)

    assert first is not None
    assert first == second


def test_submit_skips_non_video(clean_database, media):
    media.media_type = MediaType.AUDIO
    assert sync_submit_sprites_job(media, user_id=media.owner_id) is None


def test_submit_retires_a_cancelled_row(clean_database, media, submittable):
    """A cancelled sprite row must not block regeneration.

    ix_task_records_active_unique counts CANCELLED as active, so the row has to leave
    that predicate entirely — setting deleted_at alone would not free the slot.
    """
    first = sync_submit_sprites_job(media, user_id=media.owner_id)
    tr_repo.sync_update_one(first, {'status': TaskStatus.CANCELLED})

    second = sync_submit_sprites_job(media, user_id=media.owner_id, revive_cancelled=True)

    retired = tr_repo.sync_get_task_by_task_id(first)
    assert retired.status == TaskStatus.DELETED
    assert retired.deleted_at is not None
    assert second is not None and second != first, 'the replacement row must get the slot'


def test_dispatches_the_chain_row_in_place(clean_database, media, submittable):
    """The chain row is inserted at populate time with no queue_sequence."""
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id='chain-sprite',
                task_type=TaskType.SPRITE_GENERATION,
                status=TaskStatus.QUEUED,
                status_message='Waiting for download to finish...',
                download_job_url=MEDIA_URL,
                media_type=MediaType.VIDEO,
                upstream_task_ids=['chain-download'],
            )
        )
        session.commit()
    finally:
        session.close()

    returned = sync_submit_sprites_job(media, user_id=media.owner_id)

    assert returned == 'chain-sprite', 'must reuse the pre-created row, not insert a second'
    row = tr_repo.sync_get_task_by_task_id('chain-sprite')
    assert row.queue_sequence is not None
    assert row.status_message == 'Waiting to generate sprite sheet...'


def test_already_dispatched_row_is_not_resubmitted(clean_database, media, submittable):
    first = sync_submit_sprites_job(media, user_id=media.owner_id)

    with patch('tasks.sprites._dispatch_sprite_row') as mock_dispatch:
        second = sync_submit_sprites_job(media, user_id=media.owner_id)

    assert first == second
    mock_dispatch.assert_not_called()


def test_cancelled_row_is_respected_by_the_automatic_path(clean_database, media, submittable):
    """Cancelling an SPR row is the only way to decline previews mid-download."""
    first = sync_submit_sprites_job(media, user_id=media.owner_id)
    tr_repo.sync_update_one(first, {'status': TaskStatus.CANCELLED})

    assert sync_submit_sprites_job(media, user_id=media.owner_id) is None
    assert tr_repo.sync_get_task_by_task_id(first).status == TaskStatus.CANCELLED
