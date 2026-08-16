import os
import subprocess

from config import settings
from logger import logger
from models import MediaType
from orchestrator import JobContext
from repositories import clips as clips_repo
from repositories import media_details as md_repo
from tasks.ffmpeg import run_ffmpeg_cancellable

FFMPEG_CLIP_TIMEOUT_SECONDS = 600


def _build_ffmpeg_clip_command(
    input_path: str,
    output_path: str,
    start_time: float,
    duration: float,
    is_video: bool,
) -> list[str]:
    """Build FFmpeg command for creating a clip.

    Args:
        input_path: Path to source media file
        output_path: Path for output clip file
        start_time: Start time in seconds
        duration: Duration of clip in seconds
        is_video: True for video clips, False for audio-only

    Returns:
        List of command arguments for subprocess
    """
    # Common options: overwrite output, seek to start, input file, duration
    base_cmd = [
        'ffmpeg',
        '-y',
        '-ss',
        str(start_time),
        '-i',
        input_path,
        '-t',
        str(duration),
    ]

    if is_video:
        # Video: re-encode with H.264/AAC for frame-accurate cuts
        return [
            *base_cmd,
            '-c:v',
            'libx264',
            '-c:a',
            'aac',
            '-preset',
            'fast',
            '-crf',
            '23',
            output_path,
        ]
    # Audio: encode to MP3 at 192kbps
    return [*base_cmd, '-acodec', 'libmp3lame', '-ab', '192k', output_path]


def run_clip_job(ctx: JobContext, clip_data: dict) -> dict:
    """Create a clip from a media file using FFmpeg.

    Args:
        clip_data: dict containing:
            - clip_id: int - The clip record ID
            - media_details_id: int - Source media ID
            - start_time: float - Start time in seconds
            - end_time: float - End time in seconds
            - media_type: str - 'AUDIO' or 'VIDEO'

    Returns:
        dict with clip_id and file_path
    """
    clip_id = clip_data['clip_id']
    media_details_id = clip_data['media_details_id']
    start_time = clip_data['start_time']
    end_time = clip_data['end_time']
    media_type = clip_data['media_type']
    duration = end_time - start_time

    logger.info(
        f'Creating clip {clip_id} from media {media_details_id}: {start_time}s - {end_time}s'
    )

    source_media = md_repo.sync_get_media_details_by_id(media_details_id)
    if not source_media or not source_media.file_path:
        msg = f'Source media {media_details_id} not found or has no file'
        raise ValueError(msg)

    source_path = source_media.file_path

    is_video = media_type == MediaType.VIDEO.value
    base_path = settings.storage.video_path if is_video else settings.storage.audio_path
    extension = '.mp4' if is_video else '.mp3'

    clips_dir = os.path.join(base_path, 'clips')
    os.makedirs(clips_dir, exist_ok=True)

    output_path = os.path.join(clips_dir, f'clip_{clip_id}{extension}')

    cmd = _build_ffmpeg_clip_command(source_path, output_path, start_time, duration, is_video)
    logger.info(f'Running FFmpeg command: {" ".join(cmd)}')

    try:
        result = run_ffmpeg_cancellable(
            cmd, FFMPEG_CLIP_TIMEOUT_SECONDS, cancel_event=ctx.cancel_event
        )
        if result.returncode != 0:
            logger.error(f'FFmpeg stderr: {result.stderr}')
            msg = f'FFmpeg failed with return code {result.returncode}'
            raise RuntimeError(msg)
    except subprocess.TimeoutExpired as e:
        msg = 'FFmpeg timed out after 10 minutes'
        raise RuntimeError(msg) from e

    if not os.path.exists(output_path):
        msg = f'FFmpeg did not create output file: {output_path}'
        raise RuntimeError(msg)

    clips_repo.sync_update_clip(
        clip_id,
        {
            'file_path': output_path,
            'duration': duration,
        },
    )

    logger.info(f'Successfully created clip {clip_id} at {output_path}')

    return {'clip_id': clip_id, 'file_path': output_path}
