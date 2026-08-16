import contextlib
import gzip
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from math import ceil, floor

from cachetools import TTLCache
from sqlalchemy import text

import repositories.settings as settings_repo
import repositories.task_records as task_repo
import repositories.transcript_blocks as tb_repo
from config import settings
from database import db
from logger import logger
from models import MediaDetails, TaskStatus, TranscriptBlock
from progress_publisher import publish_progress
from services.embeddings import OnnxEmbedder
from ytdlp.subtitles import find_subtitle_file, parse_subtitle_file

# NOTE: faster_whisper is imported lazily inside the functions that use it.
# This module is imported by the API process (for search) and by task
# registration — a top-level import would load ctranslate2 in every process
# instead of only the ML child.

# TTL bounds how long a stale entry can outlive an access change: results are
# per-user but there is no invalidation on share/unshare or new transcripts, so
# without expiry a revoked user keeps cached hits until LRU eviction.
semantic_cache = TTLCache(maxsize=128, ttl=300)

FFPROBE_TIMEOUT_SECONDS = 10
FFMPEG_EXTRACT_TIMEOUT_SECONDS = 600
FFMPEG_CHUNK_TIMEOUT_SECONDS = 120


class TranscriptCancelled(Exception):  # noqa: N818 — control-flow signal, not an error condition
    """Raised when a transcript task's TaskRecord.status has been set to CANCELLED."""


def _check_transcript_cancelled(task_id: str | None) -> None:
    """Poll the DB for task cancellation. Raises TranscriptCancelled if cancelled.

    Used for cooperative cancellation as a fallback to the SIGTERM the ML child
    receives on cancel: long-running work periodically calls this helper to
    notice a CANCELLED status written by the API and exit gracefully.
    """
    if not task_id:
        return
    record = task_repo.sync_get_task_by_task_id(task_id)
    if record is not None and record.status == TaskStatus.CANCELLED:
        msg = f'Task {task_id} cancelled by user'
        raise TranscriptCancelled(msg)


def _get_transcript_settings() -> tuple[int, int]:
    """Get transcript chunk and block duration from settings.

    Returns:
        Tuple of (chunk_duration, block_duration) in seconds.
    """
    settings = settings_repo.sync_get_settings()
    return settings.transcript_chunk_duration, settings.transcript_block_duration


def _get_whisper_cache_path(media_file_path: str) -> str:
    base_path = os.path.splitext(media_file_path)[0]
    return f'{base_path}.whisper.json.gz'


def _save_whisper_cache(
    media_file_path: str,
    raw_segments: list[tuple[float, float, str]],
    whisper_model: str,
) -> str | None:
    """Save raw whisper segments to a gzip-compressed JSON cache file.

    Returns the cache file path on success, None on failure.
    """
    cache_path = _get_whisper_cache_path(media_file_path)
    cache_data = {
        'version': 1,
        'source': 'whisper',
        'whisper_model': whisper_model,
        'created_at': datetime.now(UTC).isoformat(),
        'segment_count': len(raw_segments),
        'segments': [[s, e, t] for s, e, t in raw_segments],
    }
    try:
        with gzip.open(cache_path, 'wt', encoding='utf-8') as f:
            json.dump(cache_data, f)
        logger.info(f'Saved whisper cache ({len(raw_segments)} segments) to {cache_path}')
    except OSError as e:
        logger.warning(f'Failed to save whisper cache: {e}')
        return None
    else:
        return cache_path


def _load_whisper_cache(
    media_file_path: str, expected_model: str | None = None
) -> list[tuple[float, float, str]] | None:
    """Load raw whisper segments from a gzip-compressed JSON cache file.

    Returns None if the cache file is missing, corrupt, or was generated with
    a different whisper model than expected_model (stale cache).
    """
    cache_path = _get_whisper_cache_path(media_file_path)
    if not os.path.exists(cache_path):
        return None

    try:
        with gzip.open(cache_path, 'rt', encoding='utf-8') as f:
            cache_data = json.load(f)
    except (OSError, json.JSONDecodeError, EOFError) as e:
        logger.warning(f'Failed to read whisper cache {cache_path}: {e}')
        return None

    if cache_data.get('version') != 1 or cache_data.get('source') != 'whisper':
        logger.warning(f'Incompatible whisper cache format in {cache_path}')
        return None

    if expected_model and cache_data.get('whisper_model') != expected_model:
        logger.info(
            f'Whisper model changed ({cache_data.get("whisper_model")} → {expected_model}), '
            f'ignoring cache'
        )
        return None

    segments = cache_data.get('segments', [])
    logger.info(f'Using cached whisper transcript ({len(segments)} segments) from {cache_path}')
    return [(s, e, t) for s, e, t in segments]


def get_media_duration(file_path: str) -> float:
    """Get duration of media file in seconds"""
    result = subprocess.run(
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
        capture_output=True,
        text=True,
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    stdout = result.stdout.strip()
    if result.returncode != 0 or not stdout:
        stderr_msg = result.stderr.strip() if result.stderr else 'no stderr output'
        msg = f'ffprobe failed for {file_path} (returncode={result.returncode}): {stderr_msg}'
        raise ValueError(msg)
    return float(stdout)


def extract_transcript_audio(video_path: str) -> str:
    """
    Extract low-bitrate audio optimized for transcription

    Returns:
        Path to extracted audio file
    """
    base_path = os.path.splitext(video_path)[0]
    audio_path = f'{base_path}_audio_transcript.mp3'

    subprocess.run(
        [
            'ffmpeg',
            '-i',
            video_path,
            '-vn',  # No video
            '-acodec',
            'libmp3lame',
            '-ab',
            '32k',  # 32 kbps
            '-ar',
            '16000',  # 16 kHz
            '-ac',
            '1',  # Mono
            '-y',
            audio_path,
        ],
        check=True,
        capture_output=True,
        timeout=FFMPEG_EXTRACT_TIMEOUT_SECONDS,
    )

    return audio_path


def create_audio_chunks(
    file_path: str, chunk_duration: int | None = None
) -> tuple[list[tuple[str, float]], str]:
    """
    Split audio file into chunks for memory-efficient processing.

    Args:
        file_path: Path to the audio file
        chunk_duration: Duration of each chunk in seconds (uses setting if not provided)

    Returns:
        Tuple of (list of (chunk_path, time_offset) tuples, temp_directory_path)
    """
    if chunk_duration is None:
        chunk_duration, _ = _get_transcript_settings()

    duration = get_media_duration(file_path)
    chunks = []

    temp_dir = tempfile.mkdtemp(prefix='transcript_chunks_')

    offset = 0.0
    chunk_index = 0

    while offset < duration:
        chunk_path = os.path.join(temp_dir, f'chunk_{chunk_index:03d}.mp3')

        # Copy codec for speed: audio is already optimized, no re-encoding needed
        subprocess.run(
            [
                'ffmpeg',
                '-i',
                file_path,
                '-ss',
                str(offset),
                '-t',
                str(chunk_duration),
                '-acodec',
                'copy',
                '-y',
                chunk_path,
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_CHUNK_TIMEOUT_SECONDS,
        )

        chunks.append((chunk_path, offset))
        logger.debug(f'Created chunk {chunk_index} at offset {offset}s: {chunk_path}')

        offset += chunk_duration
        chunk_index += 1

    logger.info(f'Split {file_path} into {len(chunks)} chunks of {chunk_duration}s each')
    return chunks, temp_dir


def _aggregate_segments_into_blocks(
    raw_segments: list[tuple[float, float, str]],
    media_details_id: int,
    block_duration: int | None = None,
    transcript_model: str | None = None,
) -> list[TranscriptBlock]:
    """
    Aggregate raw segments into TranscriptBlocks based on block_duration setting.

    Args:
        raw_segments: List of (start, end, text) tuples from whisper or subtitle parsing.
        media_details_id: ID of the media this transcript belongs to.
        block_duration: Duration in seconds for grouping segments into blocks.
        transcript_model: Model name to store on blocks. Defaults to whisper model from config.
    """
    if not raw_segments:
        return []

    if block_duration is None:
        _, block_duration = _get_transcript_settings()

    transcript_blocks = []
    block_text = ''
    block_start = floor(raw_segments[0][0])
    if transcript_model is None:
        transcript_model = settings.transcription.whisper_model

    for start_time, end_time, segment_text in raw_segments:
        if (floor(start_time) - block_start) > block_duration:
            transcript_blocks.append(
                TranscriptBlock(
                    text=block_text.strip(),
                    start_time=block_start,
                    end_time=ceil(end_time),
                    media_details_id=media_details_id,
                    transcript_model=transcript_model,
                )
            )
            block_text = ''
            block_start = floor(start_time)

        block_text += f' {segment_text.strip()}'

    if block_text.strip():
        transcript_blocks.append(
            TranscriptBlock(
                text=block_text.strip(),
                start_time=block_start,
                end_time=ceil(raw_segments[-1][1]),
                media_details_id=media_details_id,
                transcript_model=transcript_model,
            )
        )

    return transcript_blocks


def generate_raw_segments(
    file_path: str,
    media_id: int | None = None,
    chunk_duration: int | None = None,
    task_id: str | None = None,
    user_id: int | None = None,
) -> list[tuple[float, float, str]]:
    """Run Whisper on an audio file and return raw (start, end, text) segments.

    Handles both short files (direct processing) and long files (chunk-based).
    """
    logger.info('Generating raw whisper segments for %s', file_path)
    _check_transcript_cancelled(task_id)

    if chunk_duration is None:
        chunk_duration, _ = _get_transcript_settings()

    if not os.path.exists(file_path):
        logger.error(f'File not found: {file_path}')
        return []

    duration = get_media_duration(file_path)
    model_name = settings.transcription.whisper_model
    cpu_threads = settings.transcription.whisper_cpu_threads
    num_workers = settings.transcription.whisper_num_workers
    raw_segments: list[tuple[float, float, str]] = []

    # Check before the multi-second Whisper model load for an already-cancelled task.
    _check_transcript_cancelled(task_id)
    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_name,
        device='cpu',
        compute_type='int8',
        cpu_threads=cpu_threads,
        num_workers=num_workers,
    )

    if duration <= chunk_duration:
        logger.info(f'Short file ({duration:.1f}s), processing directly')
        # Short-file path has no mid-transcribe cancellation opportunity; check once here.
        _check_transcript_cancelled(task_id)
        segments, _ = model.transcribe(
            file_path,
            vad_filter=True,
            vad_parameters={'min_silence_duration_ms': 1000, 'speech_pad_ms': 400},
        )

        raw_segments.extend((segment.start, segment.end, segment.text) for segment in segments)

        if task_id and media_id:
            update_progress(task_id, media_id, 100.0, 'Transcription complete', user_id=user_id)

        return raw_segments

    logger.info(f'Long file ({duration:.1f}s), processing in {chunk_duration}s chunks')
    chunks, temp_dir = create_audio_chunks(file_path, chunk_duration)
    total_chunks = len(chunks)

    try:
        for chunk_index, (chunk_path, time_offset) in enumerate(chunks):
            # Cooperative cancellation point: each chunk boundary is a chance
            # to notice a CANCELLED status and bail gracefully.
            _check_transcript_cancelled(task_id)
            logger.info(f'Processing chunk {chunk_index + 1}/{total_chunks}')
            segments, _ = model.transcribe(
                chunk_path,
                vad_filter=True,
                vad_parameters={'min_silence_duration_ms': 1000, 'speech_pad_ms': 400},
            )

            raw_segments.extend(
                (segment.start + time_offset, segment.end + time_offset, segment.text)
                for segment in segments
            )

            with contextlib.suppress(OSError):
                os.remove(chunk_path)

            if task_id and media_id:
                progress = (chunk_index + 1) / total_chunks * 100
                status_msg = f'{chunk_index + 1}/{total_chunks} chunks processed'
                update_progress(task_id, media_id, progress, status_msg, user_id=user_id)

        logger.info('Completed processing all chunks')

        if task_id and media_id:
            update_progress(task_id, media_id, 100.0, 'Transcription complete', user_id=user_id)
    finally:
        try:
            shutil.rmtree(temp_dir)
        except OSError as e:
            logger.warning(f'Failed to clean up temp directory: {e}')

    return raw_segments


def update_progress(
    task_id: str,
    _media_id: int,
    progress: float,
    status_message: str | None = None,
    user_id: int | None = None,
):
    """Update transcript progress (sync) and publish via SSE.

    Args:
        user_id: Owner of the media. Required for the event to reach a non-admin
            subscriber — the SSE stream drops events with no user_id.
    """
    progress_rounded = round(progress, 2)
    logger.info(f'Transcript progress {progress_rounded}% for task {task_id}')

    task_update = {'percent_complete': int(progress_rounded)}
    if status_message:
        task_update['status_message'] = status_message
    task_repo.sync_update_one(task_id, task_update)

    published = publish_progress(task_id, task_update, user_id=user_id)
    if not published:
        logger.warning(f'Failed to publish transcript progress for task {task_id}')


def _try_external_subtitles(
    file_path: str,
    media_details_id: int,
    task_id: str | None,
    force_whisper: bool,
    force_recompute: bool,
    user_id: int | None = None,
) -> list[TranscriptBlock] | None:
    """Try to build transcript blocks from external subtitle files.

    Returns None if no subtitles found or if forced to use whisper.
    """
    if force_whisper or force_recompute:
        return None

    subtitle_path = find_subtitle_file(file_path)
    if not subtitle_path:
        return None

    raw_segments = parse_subtitle_file(subtitle_path)
    if not raw_segments:
        return None

    logger.info(f'Using external subtitles for transcript: {subtitle_path}')
    if task_id and media_details_id:
        update_progress(
            task_id,
            media_details_id,
            100.0,
            'Transcript from external subtitles',
            user_id=user_id,
        )

    model_name = (
        'yt-dlp-subtitles-json3' if subtitle_path.endswith('.json3') else 'yt-dlp-subtitles-vtt'
    )
    return _aggregate_segments_into_blocks(
        raw_segments, media_details_id, transcript_model=model_name
    )


def _try_cached_whisper(
    file_path: str,
    media_details_id: int,
    task_id: str | None,
    whisper_model_name: str,
    force_recompute: bool,
    user_id: int | None = None,
) -> list[TranscriptBlock] | None:
    """Try to build transcript blocks from a cached whisper file on disk.

    Returns None if no valid cache exists or if force_recompute is set.
    """
    if force_recompute:
        return None

    cached_segments = _load_whisper_cache(file_path, whisper_model_name)
    if not cached_segments:
        return None

    if task_id and media_details_id:
        update_progress(
            task_id,
            media_details_id,
            100.0,
            'Transcript from cached whisper file',
            user_id=user_id,
        )

    return _aggregate_segments_into_blocks(cached_segments, media_details_id)


def _run_fresh_transcription(
    file_path: str,
    media_details_id: int,
    task_id: str | None,
    whisper_model_name: str,
    user_id: int | None = None,
) -> list[TranscriptBlock]:
    audio_path = extract_transcript_audio(file_path)
    try:
        raw_segments = generate_raw_segments(
            audio_path, media_id=media_details_id, task_id=task_id, user_id=user_id
        )
    finally:
        with contextlib.suppress(OSError):
            os.remove(audio_path)

    if raw_segments:
        _save_whisper_cache(file_path, raw_segments, whisper_model_name)

    return _aggregate_segments_into_blocks(raw_segments, media_details_id)


def create_transcript_blocks(
    media_details: MediaDetails,
    task_id: str | None = None,
    force_recompute: bool = False,
) -> list[TranscriptBlock]:
    """Extract audio and generate transcript blocks for media.

    Priority order:
    1. External subtitles (unless force_whisper or force_recompute)
    2. Cached whisper segments from disk (unless force_recompute)
    3. Fresh Whisper transcription (saves cache afterward)

    Args:
        media_details: The media to transcribe.
        task_id: task ID for progress tracking.
        force_recompute: If True, delete cached whisper file and re-run Whisper.
    """
    app_settings = settings_repo.sync_get_settings()
    whisper_model_name = settings.transcription.whisper_model

    if force_recompute:
        cache_path = _get_whisper_cache_path(media_details.file_path)
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                logger.info(f'Deleted whisper cache for force recompute: {cache_path}')
            except OSError as e:
                logger.warning(f'Failed to delete whisper cache: {e}')

    result = _try_external_subtitles(
        media_details.file_path,
        media_details.id,
        task_id,
        app_settings.force_whisper_transcription,
        force_recompute,
        user_id=media_details.owner_id,
    )
    if result is not None:
        return result

    result = _try_cached_whisper(
        media_details.file_path,
        media_details.id,
        task_id,
        whisper_model_name,
        force_recompute,
        user_id=media_details.owner_id,
    )
    if result is not None:
        return result

    return _run_fresh_transcription(
        media_details.file_path,
        media_details.id,
        task_id,
        whisper_model_name,
        user_id=media_details.owner_id,
    )


def _embedding_to_pgvector_str(embedding: list) -> str:
    """Convert embedding list to pgvector string format: '[0.1,0.2,...]'"""
    return '[' + ','.join(str(x) for x in embedding) + ']'


def add_embeddings(
    transcript_blocks: list[TranscriptBlock], model: OnnxEmbedder
) -> list[TranscriptBlock]:
    """
    Generate embeddings for transcript blocks and atomically persist everything.

    Delegates all DB work (delete old → insert blocks → insert embeddings) to a
    single-transaction repository method to avoid connection churn and partial writes.
    """
    if not transcript_blocks:
        return []

    text_blocks = [tb.text for tb in transcript_blocks]
    embeddings = model.encode(text_blocks, normalize_embeddings=True)
    embedding_model_name = settings.embedding.model

    for block in transcript_blocks:
        block.embedding_model = embedding_model_name

    media_details_id = transcript_blocks[0].media_details_id

    embeddings_data = [
        {'embedding': _embedding_to_pgvector_str(emb.tolist())} for emb in embeddings
    ]

    tb_repo.sync_replace_transcript_blocks_with_embeddings(
        media_details_id, transcript_blocks, embeddings_data
    )

    return transcript_blocks


# --- Async functions for FastAPI routes ---


def _quote_tsquery_term(term: str) -> str:
    escaped = term.replace('\\', '\\\\').replace("'", "''")
    return f"'{escaped}'"


def _build_fts_query(search_query: str) -> str:
    """Convert a search string into an OR-based tsquery input.

    Splits on whitespace and joins with ' | ' so that documents matching
    ANY term are returned, with ts_rank_cd ranking multi-term matches higher.

    Each term is wrapped as a quoted lexeme because to_tsquery parses operator
    syntax: an unquoted '!' or "'" out of ordinary prose is a syntax error that
    fails the whole statement. Backslash must be escaped too, and before the
    apostrophe — inside a quoted lexeme it escapes the next character, so a term
    ending in one would swallow its own closing quote. Quoting is a no-op for
    terms that already parsed.
    """
    terms = search_query.split()
    if not terms:
        return ''
    return ' | '.join(_quote_tsquery_term(t) for t in terms)


def _build_metadata_filter(prefix: str = '') -> str:
    """Build optional metadata filter clause for standard_search."""
    p = f'{prefix}.' if prefix else ''
    return f'AND ({p}title ILIKE :search OR {p}channel ILIKE :search)'


def _row_to_dict(row) -> dict:
    return {
        'transcript_block_id': row.transcript_block_id,
        'text': row.text,
        'similarity': float(row.score),
        'fts_rank': float(row.fts_rank) if row.fts_rank is not None else None,
        'start_time': row.start_time,
        'end_time': row.end_time,
        # Every consumer of a search hit is a media surface: `duration` drives the
        # clip editor's range and zoom, `thumbnail_path` the lock-screen artwork.
        # All three query builders must project the same columns or this raises.
        'media_details': {
            'id': row.md_id,
            'url': row.url,
            'title': row.title,
            'channel': row.channel,
            'media_type': row.media_type,
            'status': row.status,
            'duration': row.duration,
            'thumbnail_path': row.thumbnail_path,
        },
    }


def _build_user_access_filter(prefix: str = '') -> str:
    """Build optional user access filter clause for media_access filtering."""
    p = f'{prefix}.' if prefix else ''
    # S608: `prefix` is a hardcoded table alias chosen by the caller, never user
    # input, and the user id is bound as :user_id. Same for the three query
    # builders below, whose only interpolations are these server-built clauses.
    return f'AND {p}id IN (SELECT media_details_id FROM media_access WHERE user_id = :user_id)'  # noqa: S608


async def get_hybrid_search_results(
    model: OnnxEmbedder,
    search_query: str,
    standard_search: str | None = None,
    semantic_weight: float = 0.5,
    limit: int = 100,
    user_id: int | None = None,
) -> list[dict]:
    """
    Search transcript blocks using hybrid keyword + vector search with Reciprocal Rank Fusion.

    Three modes based on semantic_weight:
    - 1.0: Pure semantic (pgvector cosine similarity)
    - 0.0: Pure keyword (native PostgreSQL FTS)
    - 0 < weight < 1: Hybrid RRF combining both rankings

    Args:
        user_id: Optional user ID to filter by media_access. None = no filter (admin view).
    """
    cache_key = (search_query, standard_search, limit, semantic_weight, user_id)
    if cache_key in semantic_cache:
        return semantic_cache[cache_key]

    metadata_filter_md = _build_metadata_filter('md')
    metadata_clause = metadata_filter_md if standard_search else ''
    access_clause = _build_user_access_filter('md') if user_id is not None else ''

    if semantic_weight == 1.0:
        results = await _semantic_search(
            model,
            search_query,
            standard_search,
            metadata_clause,
            limit,
            access_clause=access_clause,
            user_id=user_id,
        )
    elif semantic_weight == 0.0:
        results = await _keyword_search(
            model,
            search_query,
            standard_search,
            metadata_clause,
            limit,
            access_clause=access_clause,
            user_id=user_id,
        )
    else:
        results = await _hybrid_rrf_search(
            model,
            search_query,
            standard_search,
            metadata_clause,
            semantic_weight,
            limit,
            access_clause=access_clause,
            user_id=user_id,
        )

    semantic_cache[cache_key] = results
    return results


async def _semantic_search(
    model: OnnxEmbedder,
    search_query: str,
    standard_search: str | None,
    metadata_clause: str,
    limit: int,
    access_clause: str = '',
    user_id: int | None = None,
) -> list[dict]:
    """Pure vector cosine similarity search."""
    query_embedding = model.encode([search_query], normalize_embeddings=True)[0]
    query_str = _embedding_to_pgvector_str(query_embedding.tolist())

    sql = f"""
        SELECT
            tb.id as transcript_block_id,
            tb.text,
            tb.start_time,
            tb.end_time,
            md.id as md_id,
            md.url,
            md.title,
            md.channel,
            md.media_type,
            md.status,
            md.duration,
            md.thumbnail_path,
            1.0 - (te.embedding <=> :query) as score,
            NULL::float as fts_rank
        FROM transcript_embeddings te
        JOIN transcript_blocks tb ON tb.id = te.transcript_block_id
        JOIN media_details md ON md.id = tb.media_details_id
        WHERE 1=1 {metadata_clause} {access_clause}
        ORDER BY te.embedding <=> :query ASC
        LIMIT :limit
    """  # noqa: S608

    params: dict = {'query': query_str, 'limit': limit}
    if standard_search:
        params['search'] = f'%{standard_search}%'
    if user_id is not None:
        params['user_id'] = user_id

    async with db.get_async_session() as session:
        result = await session.execute(text(sql), params)
        rows = result.fetchall()

    return [_row_to_dict(row) for row in rows]


async def _keyword_search(
    model: OnnxEmbedder,
    search_query: str,
    standard_search: str | None,
    metadata_clause: str,
    limit: int,
    access_clause: str = '',
    user_id: int | None = None,
) -> list[dict]:
    """Pure keyword search via native PostgreSQL FTS. Ranked by ts_rank_cd, display score is cosine similarity."""
    query_embedding = model.encode([search_query], normalize_embeddings=True)[0]
    query_str = _embedding_to_pgvector_str(query_embedding.tolist())
    fts_query = _build_fts_query(search_query)

    sql = f"""
        WITH fts_ranked AS (
            SELECT
                tb.id,
                ts_rank_cd(tb.text_search, to_tsquery('english', :fts_query)) AS fts_rank
            FROM transcript_blocks tb
            JOIN media_details md ON md.id = tb.media_details_id
            WHERE tb.text_search @@ to_tsquery('english', :fts_query)
                {metadata_clause} {access_clause}
            ORDER BY fts_rank DESC
            LIMIT :limit
        )
        SELECT
            tb.id as transcript_block_id,
            tb.text,
            tb.start_time,
            tb.end_time,
            md.id as md_id,
            md.url,
            md.title,
            md.channel,
            md.media_type,
            md.status,
            md.duration,
            md.thumbnail_path,
            1.0 - (te.embedding <=> :embedding) as score,
            fr.fts_rank as fts_rank
        FROM fts_ranked fr
        JOIN transcript_blocks tb ON tb.id = fr.id
        JOIN media_details md ON md.id = tb.media_details_id
        JOIN transcript_embeddings te ON te.transcript_block_id = tb.id
        ORDER BY fr.fts_rank DESC
    """  # noqa: S608

    params: dict = {'fts_query': fts_query, 'embedding': query_str, 'limit': limit}
    if standard_search:
        params['search'] = f'%{standard_search}%'
    if user_id is not None:
        params['user_id'] = user_id

    async with db.get_async_session() as session:
        result = await session.execute(text(sql), params)
        rows = result.fetchall()

    return [_row_to_dict(row) for row in rows]


async def _hybrid_rrf_search(
    model: OnnxEmbedder,
    search_query: str,
    standard_search: str | None,
    metadata_clause: str,
    semantic_weight: float,
    limit: int,
    access_clause: str = '',
    user_id: int | None = None,
) -> list[dict]:
    """Hybrid search using RRF for ranking, cosine similarity for display score."""
    query_embedding = model.encode([search_query], normalize_embeddings=True)[0]
    query_str = _embedding_to_pgvector_str(query_embedding.tolist())
    fts_query = _build_fts_query(search_query)

    keyword_weight = 1.0 - semantic_weight
    candidate_limit = limit * 3  # Fetch more candidates for better fusion

    sql = f"""
        WITH vector_search AS (
            SELECT
                te.transcript_block_id AS id,
                ROW_NUMBER() OVER (ORDER BY te.embedding <=> :embedding) AS rank
            FROM transcript_embeddings te
            JOIN transcript_blocks tb ON tb.id = te.transcript_block_id
            JOIN media_details md ON md.id = tb.media_details_id
            WHERE 1=1 {metadata_clause} {access_clause}
            ORDER BY te.embedding <=> :embedding ASC
            LIMIT :candidate_limit
        ),
        keyword_search AS (
            SELECT
                tb.id,
                ts_rank_cd(tb.text_search, to_tsquery('english', :fts_query)) AS fts_rank,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(tb.text_search, to_tsquery('english', :fts_query)) DESC
                ) AS rank
            FROM transcript_blocks tb
            JOIN media_details md ON md.id = tb.media_details_id
            WHERE tb.text_search @@ to_tsquery('english', :fts_query)
                {metadata_clause} {access_clause}
            ORDER BY fts_rank DESC
            LIMIT :candidate_limit
        )
        SELECT
            tb.id as transcript_block_id,
            tb.text,
            tb.start_time,
            tb.end_time,
            md.id as md_id,
            md.url,
            md.title,
            md.channel,
            md.media_type,
            md.status,
            md.duration,
            md.thumbnail_path,
            1.0 - (te.embedding <=> :embedding) as score,
            k.fts_rank as fts_rank
        FROM transcript_blocks tb
        JOIN media_details md ON md.id = tb.media_details_id
        JOIN transcript_embeddings te ON te.transcript_block_id = tb.id
        LEFT JOIN vector_search v ON tb.id = v.id
        LEFT JOIN keyword_search k ON tb.id = k.id
        WHERE v.id IS NOT NULL OR k.id IS NOT NULL
        ORDER BY
            :semantic_weight * COALESCE(1.0 / (60 + v.rank), 0.0) +
            :keyword_weight * COALESCE(1.0 / (60 + k.rank), 0.0) DESC
        LIMIT :limit
    """  # noqa: S608

    params: dict = {
        'embedding': query_str,
        'fts_query': fts_query,
        'semantic_weight': semantic_weight,
        'keyword_weight': keyword_weight,
        'candidate_limit': candidate_limit,
        'limit': limit,
    }
    if standard_search:
        params['search'] = f'%{standard_search}%'
    if user_id is not None:
        params['user_id'] = user_id

    async with db.get_async_session() as session:
        result = await session.execute(text(sql), params)
        rows = result.fetchall()

    return [_row_to_dict(row) for row in rows]
