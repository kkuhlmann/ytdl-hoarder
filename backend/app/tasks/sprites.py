import json
import math
import os
import subprocess
import time
import uuid
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError

from logger import logger
from models import MediaType, TaskRecord, TaskStatus, TaskType
from orchestrator import JobContext, SkipJob
from progress_publisher import publish_progress, publish_status_change
from repositories import media_details as md_repo
from repositories import task_records as tr_repo
from repositories.task_records.crud import SUBSCRIPTION_DOWNLOAD_PRIORITY
from services.cleanup import delete_file
from tasks.ffmpeg import run_ffmpeg_cancellable

FFMPEG_SPRITES_TIMEOUT_SECONDS = 900
SPRITE_FRAME_WIDTH = 160
SPRITE_FRAME_HEIGHT = 90
MAX_COLUMNS = 10
MAX_TOTAL_FRAMES = 500

# The tile filter emits nothing until EOF, so ffmpeg cannot report progress on this
# pipeline (measured: one -progress block, at the end). The row reports elapsed time
# instead, throttled well below the poll rate so a 15-minute run doesn't issue ~1800
# DB writes.
SPRITES_ELAPSED_UPDATE_SECONDS = 5.0

ACTIVE_SPRITE_STATUSES = [TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.RETRY]


def _calculate_interval(duration: float) -> float:
    if duration < 300:
        interval = 2
    elif duration < 1800:
        interval = 5
    else:
        interval = 10

    # Cap total frames to avoid enormous sprite sheets
    total_frames = math.ceil(duration / interval)
    if total_frames > MAX_TOTAL_FRAMES:
        interval = duration / MAX_TOTAL_FRAMES

    return interval


def sprite_paths(file_path: str) -> tuple[str, str]:
    """(sprite sheet, metadata sidecar) paths for a media file."""
    base_path = os.path.splitext(file_path)[0]
    return base_path + '.sprites.jpg', base_path + '.sprites.json'


def delete_partial_sprite_output(media_details_id: int | None) -> None:
    """Remove sprite output left behind by a killed or interrupted run.

    ffmpeg's -y truncates the target at open, so an aborted run leaves a corrupt
    JPEG that get_sprites would happily serve.
    """
    if media_details_id is None:
        return
    media = md_repo.sync_get_media_details_by_id(media_details_id)
    if not media or not media.file_path:
        return
    sprite_path, metadata_path = sprite_paths(media.file_path)
    # The sidecar is written last, so a sheet without one is a truncated run.
    if os.path.exists(sprite_path) and not os.path.exists(metadata_path):
        delete_file(sprite_path)


def _build_ffmpeg_sprites_command(
    input_path: str,
    output_path: str,
    interval: float,
    columns: int,
    rows: int,
) -> list[str]:
    vf = (
        f'fps=1/{interval},'
        f'scale={SPRITE_FRAME_WIDTH}:{SPRITE_FRAME_HEIGHT}'
        f':force_original_aspect_ratio=decrease,'
        f'pad={SPRITE_FRAME_WIDTH}:{SPRITE_FRAME_HEIGHT}'
        f':(ow-iw)/2:(oh-ih)/2,'
        f'tile={columns}x{rows}'
    )
    return [
        'ffmpeg',
        '-y',
        '-i',
        input_path,
        '-vf',
        vf,
        '-frames:v',
        '1',
        '-qscale:v',
        '5',
        output_path,
    ]


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}h{minutes:02d}m'
    if minutes:
        return f'{minutes}m{secs:02d}s'
    return f'{secs}s'


def _create_elapsed_reporter(task_id: str, user_id: int | None) -> Callable[[], None]:
    """Tick callback that keeps the task row's message showing elapsed run time."""
    started = time.monotonic()
    last_write = started

    def report() -> None:
        nonlocal last_write
        now = time.monotonic()
        if now - last_write < SPRITES_ELAPSED_UPDATE_SECONDS:
            return
        last_write = now
        update_fields = {
            'status_message': f'Generating sprite sheet... {_format_elapsed(now - started)}'
        }
        tr_repo.sync_update_one(task_id, update_fields)
        publish_progress(task_id, update_fields, user_id=user_id)

    return report


DISPATCH_STATUS_MESSAGE = 'Waiting to generate sprite sheet...'


def _dispatch_sprite_row(
    task_id: str,
    media,
    *,
    priority: int,
    force: bool,
    user_id: int | None,
    queue_sequence: int | None = None,
) -> str:
    """Give a sprite row its queue_sequence and hand it to the orchestrator."""
    from orchestrator import SPRITES_JOB, JobSpec, OrchestratorNotRunningError, orch

    if queue_sequence is None:
        queue_sequence = tr_repo.sync_get_next_queue_sequence()
        tr_repo.sync_update_one(
            task_id,
            {
                'queue_sequence': queue_sequence,
                'priority': priority,
                'status_message': DISPATCH_STATUS_MESSAGE,
            },
        )

    publish_status_change(
        task_id, TaskStatus.QUEUED.value, DISPATCH_STATUS_MESSAGE, user_id=user_id
    )

    payload = {'media_details_id': media.id, 'user_id': user_id, 'force': force}
    try:
        orch.submit_from_thread(
            JobSpec(
                job_name=SPRITES_JOB,
                args=(payload,),
                task_id=task_id,
                priority=priority,
                queue_sequence=queue_sequence,
                user_id=user_id,
            )
        )
    except OrchestratorNotRunningError:
        logger.warning('Orchestrator not running; sprite task left queued for startup recovery')
    return task_id


def sync_submit_sprites_job(
    media,
    *,
    user_id: int | None,
    priority: int = SUBSCRIPTION_DOWNLOAD_PRIORITY,
    force: bool = False,
    revive_cancelled: bool = False,
) -> str | None:
    """Dispatch sprite generation for a video, creating the task row if needed.

    The row usually already exists: the download chain inserts it QUEUED at populate
    time with no queue_sequence, which is the marker for "not dispatched yet".

    Returns the task_id, or None when the media can't have sprites, the user
    cancelled this chain's sprite row, or another caller won the insert race.
    """
    if not media.file_path or not media.media_type:
        return None
    if media.media_type.value != MediaType.VIDEO.value:
        return None

    media_type = media.media_type.value
    existing = tr_repo.sync_find_active_by_url_and_type(
        media.url, media_type, TaskType.SPRITE_GENERATION, ACTIVE_SPRITE_STATUSES
    )
    if existing and existing.queue_sequence is not None:
        return existing.task_id
    if existing:
        return _dispatch_sprite_row(
            existing.task_id,
            media,
            priority=existing.priority if existing.priority is not None else priority,
            force=force,
            # The row's own user_id, so SSE filtering matches what the row shows.
            user_id=existing.user_id,
        )

    if not revive_cancelled and tr_repo.sync_find_active_by_url_and_type(
        media.url, media_type, TaskType.SPRITE_GENERATION, [TaskStatus.CANCELLED]
    ):
        # Cancelling the row is the only way to decline previews for a download that
        # hasn't finished yet, so re-creating one here would make that button a no-op.
        # A new download chain still re-plans sprites; the manual endpoint overrides.
        return None

    tr_repo.sync_release_cancelled_task_slot(media.url, media_type, TaskType.SPRITE_GENERATION)

    task_id = str(uuid.uuid4())
    queue_sequence = tr_repo.sync_get_next_queue_sequence()
    record = TaskRecord(
        task_id=task_id,
        task_type=TaskType.SPRITE_GENERATION,
        status=TaskStatus.QUEUED,
        status_message=DISPATCH_STATUS_MESSAGE,
        title=media.title,
        channel=media.channel,
        media_type=media.media_type,
        download_job_url=media.url,
        user_id=user_id,
        queue_sequence=queue_sequence,
        priority=priority,
    )
    try:
        tr_repo.sync_insert_task(record)
    except IntegrityError:
        # A sibling path queued sprites for this URL between the lookup and the
        # insert (ix_task_records_active_unique) — theirs is as good as ours.
        logger.info(f'Sprites: task already exists for {media.url}')
        return None

    return _dispatch_sprite_row(
        task_id,
        media,
        priority=priority,
        force=force,
        user_id=user_id,
        queue_sequence=queue_sequence,
    )


def run_sprites_job(ctx: JobContext, payload: dict) -> dict:
    """Generate a sprite sheet from a video file for preview thumbnails.

    Extracts frames at regular intervals and tiles them into a single JPEG.
    Writes a metadata JSON sidecar alongside the sprite sheet.
    """
    media_details_id = payload['media_details_id']
    force = payload.get('force', False)

    media = md_repo.sync_get_media_details_by_id(media_details_id)
    if not media:
        msg = f'Media {media_details_id} not found'
        raise ValueError(msg)
    if not media.media_type or media.media_type.value != MediaType.VIDEO.value:
        msg = f'Media {media_details_id} is not a video'
        raise ValueError(msg)
    if not media.file_path or not os.path.exists(media.file_path):
        msg = f'Media file not found for media {media_details_id}'
        raise ValueError(msg)
    if not media.duration or media.duration <= 0:
        msg = f'Media {media_details_id} has no duration'
        raise ValueError(msg)

    sprite_path, metadata_path = sprite_paths(media.file_path)

    if not force and os.path.exists(sprite_path) and os.path.exists(metadata_path):
        status_message = 'Sprite sheet already exists'
        tr_repo.sync_update_one(
            ctx.task_id, {'status': TaskStatus.SKIPPED.value, 'status_message': status_message}
        )
        publish_status_change(
            ctx.task_id, TaskStatus.SKIPPED.value, status_message, user_id=ctx.user_id
        )
        raise SkipJob(status_message)

    interval = _calculate_interval(media.duration)
    total_frames = math.ceil(media.duration / interval)
    columns = min(MAX_COLUMNS, total_frames)
    rows = math.ceil(total_frames / columns)

    logger.info(
        f'Sprites: generating for media {media_details_id} — '
        f'{total_frames} frames, {columns}x{rows} grid, {interval:.1f}s interval'
    )

    cmd = _build_ffmpeg_sprites_command(media.file_path, sprite_path, interval, columns, rows)

    ctx.check_cancelled()
    try:
        result = run_ffmpeg_cancellable(
            cmd,
            FFMPEG_SPRITES_TIMEOUT_SECONDS,
            cancel_event=ctx.cancel_event,
            on_tick=_create_elapsed_reporter(ctx.task_id, ctx.user_id),
        )
        if result.returncode != 0:
            logger.error(f'Sprites: ffmpeg stderr: {result.stderr}')
            msg = f'FFmpeg failed with return code {result.returncode}'
            raise RuntimeError(msg)
    except subprocess.TimeoutExpired as e:
        msg = 'Sprite generation timed out after 15 minutes'
        raise RuntimeError(msg) from e

    if not os.path.exists(sprite_path):
        msg = f'FFmpeg did not create output file: {sprite_path}'
        raise RuntimeError(msg)

    metadata = {
        'width': SPRITE_FRAME_WIDTH,
        'height': SPRITE_FRAME_HEIGHT,
        'columns': columns,
        'rows': rows,
        'interval': interval,
        'total_frames': total_frames,
    }

    with open(metadata_path, 'w') as f:
        json.dump(metadata, f)

    logger.info(f'Sprites: generated for media {media_details_id} at {sprite_path}')
    return {'media_details_id': media_details_id, 'sprite_path': sprite_path}
