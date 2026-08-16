import asyncio
import contextlib
import gzip
import json
import mimetypes
import os

import aiofiles
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from dependencies import get_accessible_clip, get_accessible_media, get_required_user_id
from models import MediaType
from repositories.task_records.crud import DIRECT_DOWNLOAD_PRIORITY
from utils import sanitize_folder_name

router = APIRouter()

THUMBNAIL_CACHE_MAX_AGE_SECONDS = 86400  # 24 hours
SPRITES_CACHE_MAX_AGE_SECONDS = 604800  # 7 days

# Waveform peak generation
FFPROBE_PEAKS_TIMEOUT_SECONDS = 30
FFMPEG_PEAKS_TIMEOUT_SECONDS = 300
PEAKS_SAMPLE_RATE = 8000  # 8kHz mono → enough resolution for waveform peaks, small payload

mimetypes.add_type('video/mp4', '.m4a')
mimetypes.add_type('audio/ogg', '.ogg')
mimetypes.add_type('audio/opus', '.opus')
mimetypes.add_type('video/x-matroska', '.mkv')


# ASYNC109 is suppressed below: bounding the subprocess is this helper's entire
# purpose, and the bound must be a parameter — callers pass different limits.
async def _run_with_timeout(cmd: list[str], timeout: int) -> bytes:  # noqa: ASYNC109
    """Run a subprocess and return its stdout.

    Raises HTTPException(504) on timeout (after killing the process) and
    HTTPException(500) if the command exits non-zero.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f'{cmd[0]} timed out after {timeout}s',
        ) from e
    finally:
        # Reap on every exit path — a client disconnect cancels this coroutine
        # mid-communicate and would otherwise leave ffmpeg running unreaped.
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'{cmd[0]} failed: {stderr.decode().strip()}',
        )
    return stdout


def _read_peaks_cache(cache_path: str) -> dict:
    with gzip.open(cache_path, 'rt', encoding='utf-8') as f:
        return json.loads(f.read())


def _write_peaks_cache(cache_path: str, result: dict) -> None:
    with gzip.open(cache_path, 'wt', encoding='utf-8') as f:
        f.write(json.dumps(result))


def _bin_peaks(pcm_bytes: bytes, num_peaks: int) -> list[float]:
    """Bin raw mono float32 PCM into num_peaks max-absolute-amplitude peaks.

    Uses numpy so the work stays in C and memory stays ~O(len(pcm_bytes)):
    frombuffer views the bytes without copying, and reduceat computes the
    per-bin max/min directly, avoiding the multi-GB Python float tuple that
    struct.unpack would build for a multi-hour file.
    """
    arr = np.frombuffer(pcm_bytes, dtype='<f4')
    n = arr.shape[0]
    if n == 0:
        return []
    peaks_n = min(num_peaks, n)
    starts = (np.arange(peaks_n) * n) // peaks_n
    seg_max = np.maximum.reduceat(arr, starts).astype(np.float64)
    seg_min = np.minimum.reduceat(arr, starts).astype(np.float64)
    peaks = np.round(np.maximum(seg_max, -seg_min), 4).tolist()
    peaks.extend([0.0] * (num_peaks - len(peaks)))
    return peaks


@router.get(
    '/{id}/peaks', status_code=status.HTTP_200_OK, response_description='Get waveform peaks'
)
async def get_peaks(
    id: int,
    num_peaks: int = Query(default=8000, ge=100, le=10000),
    media_details=Depends(get_accessible_media),
):
    """Generate waveform peak data for a media file.

    Uses ffmpeg to extract audio samples and bins them into peaks.
    Results are cached as .peaks.json.gz alongside the media file.
    """
    file_path = media_details.file_path
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Media file not found for media with id {id}',
        )

    base_path = os.path.splitext(file_path)[0]
    cache_path = base_path + '.peaks.json.gz'

    if os.path.exists(cache_path):
        # Off the event loop: gzip decompress + parse of a ~50KB file is sync I/O.
        cached = await asyncio.to_thread(_read_peaks_cache, cache_path)
        # Re-bin if requested num_peaks differs from cached
        if len(cached.get('peaks', [])) == num_peaks:
            return JSONResponse(content=cached)

    probe_stdout = await _run_with_timeout(
        [
            'ffprobe',
            '-v',
            'error',
            '-show_entries',
            'format=duration',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            file_path,
        ],
        FFPROBE_PEAKS_TIMEOUT_SECONDS,
    )
    try:
        duration = float(probe_stdout.decode().strip())
    except ValueError as e:
        # ffprobe prints 'N/A' for containers without a format-level duration
        # (raw/streamed matroska, for one).
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Could not determine media duration',
        ) from e

    ffmpeg_stdout = await _run_with_timeout(
        [
            'ffmpeg',
            '-i',
            file_path,
            '-ac',
            '1',
            '-ar',
            str(PEAKS_SAMPLE_RATE),
            '-f',
            'f32le',
            '-v',
            'error',
            'pipe:1',
        ],
        FFMPEG_PEAKS_TIMEOUT_SECONDS,
    )

    # Bin samples into peaks off the event loop (CPU-bound numpy work)
    peaks = await asyncio.to_thread(_bin_peaks, ffmpeg_stdout, num_peaks)
    if not peaks:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='No audio samples extracted',
        )

    result = {'peaks': peaks, 'duration': round(duration, 2)}

    # gzip compresses ~50KB JSON to ~15KB; off the event loop like the read above.
    # Non-critical if caching fails.
    with contextlib.suppress(OSError):
        await asyncio.to_thread(_write_peaks_cache, cache_path, result)

    return JSONResponse(content=result)


@router.get(
    '/{id}/thumbnail', status_code=status.HTTP_200_OK, response_description='Get thumbnail image'
)
async def get_thumbnail(id: int, media_details=Depends(get_accessible_media)):
    """Serve the locally stored thumbnail for a media item."""
    thumb_path = media_details.thumbnail_path
    if not thumb_path or not os.path.exists(thumb_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Thumbnail not found for media with id {id}',
        )

    return FileResponse(
        thumb_path,
        media_type='image/jpeg',
        headers={'Cache-Control': f'public, max-age={THUMBNAIL_CACHE_MAX_AGE_SECONDS}'},
    )


@router.get(
    '/{id}/sprites', status_code=status.HTTP_200_OK, response_description='Get sprite sheet image'
)
async def get_sprites(id: int, media_details=Depends(get_accessible_media)):
    """Serve the sprite sheet JPEG for video preview thumbnails."""
    if not media_details.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Media file not found')

    sprite_path = os.path.splitext(media_details.file_path)[0] + '.sprites.jpg'
    if not os.path.exists(sprite_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Sprite sheet not found for media with id {id}',
        )

    return FileResponse(
        sprite_path,
        media_type='image/jpeg',
        headers={'Cache-Control': f'public, max-age={SPRITES_CACHE_MAX_AGE_SECONDS}'},
    )


@router.get(
    '/{id}/sprites/metadata',
    status_code=status.HTTP_200_OK,
    response_description='Get sprite sheet metadata',
)
async def get_sprites_metadata(id: int, media_details=Depends(get_accessible_media)):
    """Serve the sprite sheet metadata JSON for calculating frame positions."""
    if not media_details.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Media file not found')

    metadata_path = os.path.splitext(media_details.file_path)[0] + '.sprites.json'
    if not os.path.exists(metadata_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Sprite metadata not found for media with id {id}',
        )

    async with aiofiles.open(metadata_path) as f:
        metadata = json.loads(await f.read())

    return JSONResponse(content=metadata)


@router.post(
    '/{id}/sprites/generate',
    status_code=status.HTTP_200_OK,
    response_description='Generate sprite sheet',
)
async def generate_sprites(
    media_details=Depends(get_accessible_media),
    user_id: int = Depends(get_required_user_id),
):
    """Trigger sprite sheet generation for an existing video.

    Regenerates unconditionally — an explicit request should not be a no-op just
    because a sheet is already on disk.
    """
    if not media_details.media_type or media_details.media_type.value != 'VIDEO':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail='Sprite generation is only for videos'
        )
    if not media_details.file_path or not os.path.exists(media_details.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Media file not found')

    from tasks.sprites import sync_submit_sprites_job

    task_id = await asyncio.to_thread(
        sync_submit_sprites_job,
        media_details,
        user_id=user_id,
        priority=DIRECT_DOWNLOAD_PRIORITY,
        force=True,
        revive_cancelled=True,
    )
    return {'status': 'queued', 'task_id': task_id}


def _build_stream_response(
    request: Request, file_path: str, *, is_video: bool
) -> StreamingResponse:
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Media file does not exist on disk',
        )

    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail='Unsupported media type',
        )

    file_size = os.path.getsize(file_path)
    # Video is always served as video/mp4 regardless of container: browsers that
    # can play the codec will, and several refuse video/x-matroska outright.
    content_type = 'video/mp4' if is_video else mime_type

    headers = {
        'content-type': content_type,
        'accept-ranges': 'bytes',
        'content-encoding': 'identity',
        'content-length': str(file_size),
        'access-control-expose-headers': (
            'content-type, accept-ranges, content-length, content-range, content-encoding'
        ),
    }

    start = 0
    end = file_size - 1
    response_status_code = status.HTTP_200_OK

    range_header = request.headers.get('range')
    if range_header is not None:
        start, end = _get_range_header(range_header, file_size)
        size = end - start + 1
        headers['content-length'] = str(size)
        headers['content-range'] = f'bytes {start}-{end}/{file_size}'
        response_status_code = status.HTTP_206_PARTIAL_CONTENT

    return StreamingResponse(
        read_chunks(file_path, start, end),
        status_code=response_status_code,
        headers=headers,
    )


@router.get('/{id}', status_code=status.HTTP_200_OK, response_description='Stream video by ID')
async def stream_video(request: Request, id: int, media_details=Depends(get_accessible_media)):
    file_path = media_details.file_path
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Video not found for media with id {id}',
        )

    return _build_stream_response(
        request, file_path, is_video=media_details.media_type == MediaType.VIDEO
    )


async def read_chunks(file_path, start, end, chunk_size=64 * 1024):
    async with aiofiles.open(file_path, mode='rb') as f:
        await f.seek(start)
        pos = start
        while pos <= end:
            read_size = min(chunk_size, end + 1 - pos)
            data = await f.read(read_size)
            if not data:
                break
            pos += len(data)
            yield data


def _get_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    def _invalid_range():
        return HTTPException(
            status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail=f'Invalid request range (Range:{range_header!r})',
        )

    try:
        h = range_header.replace('bytes=', '').split('-')
        start = int(h[0]) if h[0] != '' else 0
        end = int(h[1]) if h[1] != '' else file_size - 1
    except ValueError:
        raise _invalid_range() from None

    if start > end or start < 0 or end > file_size - 1:
        raise _invalid_range()
    return start, end


@router.get('/clip/{id}', status_code=status.HTTP_200_OK, response_description='Stream clip by ID')
async def stream_clip(request: Request, id: int, clip=Depends(get_accessible_clip)):
    """Stream a clip file with support for range requests."""
    file_path = clip.file_path
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Clip file not found for clip with id {id}',
        )

    return _build_stream_response(request, file_path, is_video=clip.media_type == MediaType.VIDEO)


@router.get(
    '/clip/{id}/download',
    status_code=status.HTTP_200_OK,
    response_description='Download a clip file as an attachment',
)
async def download_clip(id: int, clip=Depends(get_accessible_clip)):
    """Download a clip file (audio .mp3 / video .mp4) as a browser attachment."""

    file_path = clip.file_path
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Clip file not found for clip with id {id}',
        )

    is_video = clip.media_type.value == 'VIDEO'
    extension = '.mp4' if is_video else '.mp3'
    media_type = 'video/mp4' if is_video else 'audio/mpeg'
    download_name = f'{sanitize_folder_name(clip.title)}{extension}'

    return FileResponse(file_path, media_type=media_type, filename=download_name)
