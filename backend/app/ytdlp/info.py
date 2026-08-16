from datetime import datetime

from cachetools import TTLCache, cached
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError, match_filter_func

from config import settings
from logger import logger
from repositories import settings as settings_repo
from ytdlp.cookies import cookie_session
from ytdlp.options import _get_pot_extractor_args
from ytdlp.urls import is_youtube_url, normalize_video_url

EXTRACTION_UNAVAILABLE = 'unavailable'
EXTRACTION_TRANSIENT = 'transient'

# yt-dlp message fragments that positively identify a permanently unavailable video.
# Deliberately a whitelist: a rate-limit block and a private video both surface as a
# swallowed DownloadError, and callers back off for days on 'unavailable', so anything
# unrecognized must fall through to 'transient'.
_UNAVAILABLE_ERROR_PATTERNS = (
    'private video',
    'video unavailable',
    'members-only',
    'available to members',
    # Matches both "not available in your country" and yt-dlp's actual phrasing,
    # "has not made this video available in your country".
    'available in your country',
    'blocked it in your country',
    'confirm your age',
    'age-restricted',
    'has been removed',
    'has been terminated',
)


def classify_extraction_error(error: Exception) -> str:
    """Return EXTRACTION_UNAVAILABLE or EXTRACTION_TRANSIENT for a failed extraction.

    Args:
        error: The ExtractorError/DownloadError raised by yt-dlp

    Returns:
        EXTRACTION_UNAVAILABLE only when the message positively matches a permanent
        condition; EXTRACTION_TRANSIENT for everything else, including 429s, bot
        checks, timeouts and unrecognized failures.
    """
    message = str(error).lower()
    if any(pattern in message for pattern in _UNAVAILABLE_ERROR_PATTERNS):
        return EXTRACTION_UNAVAILABLE
    return EXTRACTION_TRANSIENT


@cached(cache=TTLCache(maxsize=500, ttl=300))
def _fetch_url_info(
    url: str,
    title_filter=None,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
    max_entries: int | None = None,
) -> tuple[dict | None, str | None]:
    """Extract metadata, returning (info, failure_kind).

    failure_kind is None on success and one of EXTRACTION_UNAVAILABLE /
    EXTRACTION_TRANSIENT when extraction failed. Both public wrappers share this one
    cache, so classifying a failure costs no extra fetch.
    """
    filters = [
        '!is_live',  # Not currently live
        'live_status!=is_upcoming',  # Not an upcoming premiere
        'live_status!=is_live',  # Alternate live check
    ]

    if title_filter:
        title_filter_str = f'title ~= (?i)\\b{str(title_filter).strip().lower()}\\b'
        filters.append(title_filter_str)

    if min_duration_seconds is not None:
        filters.append(f'duration >= {min_duration_seconds}')
    if max_duration_seconds is not None:
        filters.append(f'duration <= {max_duration_seconds}')

    match_filter_text = ' & '.join(filters)
    match_filter = match_filter_func(match_filter_text)

    app_settings = settings_repo.sync_get_settings()

    options = {
        'extract_flat': True,
        'match_filter': match_filter,
        'quiet': settings.logging.level.upper() != 'DEBUG',
        'ignore_no_formats_error': True,  # We only need metadata, not formats
    }

    # yt-dlp sleeps between extraction requests, which is where nearly all of this
    # deployment's request volume is; the download-side cap does not cover it.
    if app_settings.request_sleep_seconds > 0:
        options['sleep_interval_requests'] = app_settings.request_sleep_seconds

    # Cap enumeration when only top-level channel/playlist metadata is needed
    # (e.g. resolving a channel name on subscription add). Without this, yt-dlp
    # walks the entire flat entry list just to read one top-level field.
    if max_entries is not None:
        options['playlist_items'] = f'1:{max_entries}'

    with cookie_session(metadata_only=True) as cookie_file:
        if is_youtube_url(url):
            player_clients = (
                app_settings.cookies_player_client if cookie_file else app_settings.player_client
            )
            options['extractor_args'] = {
                'youtube': {'player_client': player_clients},
                **_get_pot_extractor_args(),
            }
            if cookie_file:
                options['cookiefile'] = cookie_file

        # Impersonation is deliberately skipped here: random targets return
        # inconsistent channel info — some give only uploader_id (@ChannelName)
        # instead of channel (Channel Name) — which produces inconsistent folder names.
        try:
            with YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=False), None
        except (ExtractorError, DownloadError) as e:
            # Extractor/download errors are routine here (private, geo-blocked,
            # removed videos); a traceback per occurrence floods the log.
            logger.error(e)  # noqa: TRY400
            return None, classify_extraction_error(e)


def get_url_info(
    url: str,
    title_filter=None,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
    max_entries: int | None = None,
):
    info, _ = _fetch_url_info(
        url, title_filter, min_duration_seconds, max_duration_seconds, max_entries
    )
    return info


def get_url_info_with_failure(
    url: str,
    title_filter=None,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
    max_entries: int | None = None,
) -> tuple[dict | None, str | None]:
    """get_url_info, plus why extraction failed — see _fetch_url_info for the kinds.

    Only the populate deferral path needs the reason: it decides how long to park an
    unresolvable URL, and must not apply the multi-day backoff to a transient failure.
    """
    return _fetch_url_info(
        url, title_filter, min_duration_seconds, max_duration_seconds, max_entries
    )


def get_release_timestamp(info: dict) -> datetime | None:
    """Extract release timestamp from yt-dlp info dict.

    Returns None instead of raising when fields are missing or malformed
    (common on non-YouTube platforms).
    """
    if info.get('release_timestamp') is not None:
        try:
            return datetime.fromtimestamp(info['release_timestamp'])
        except (ValueError, OSError, OverflowError):
            pass
    upload_date = info.get('upload_date')
    if upload_date:
        try:
            return datetime.strptime(upload_date, '%Y%m%d')
        except (ValueError, TypeError):
            pass
    return None


def get_channel_from_info(info: dict) -> str | None:
    """
    Extract channel name from yt-dlp info dict.

    Different impersonation targets and player clients return channel info
    in different fields. This function checks all known field names.

    Field priority (most reliable first):
    - channel: Official channel name
    - uploader: Uploader display name
    - uploader_id: Uploader handle/ID (e.g., @ChannelName)
    - creator: Content creator (less common)
    """
    if not info:
        return None

    for field in ('channel', 'uploader', 'uploader_id', 'creator'):
        value = info.get(field)
        if value:
            return value

    return None


def _has_downloadable_formats(info: dict) -> bool:
    """True if the info dict exposes at least one real (audio- or video-bearing)
    downloadable format.

    A fully-processed VOD has these; a livestream still being processed into a VOD
    typically has none (or only a bare live manifest).
    """
    formats = info.get('formats') or []
    return any(
        f.get('vcodec') not in (None, 'none') or f.get('acodec') not in (None, 'none')
        for f in formats
    )


def is_video_ready_for_download(info: dict) -> tuple[bool, str]:
    """
    Check if a video is ready for download.

    Defers videos that are currently live or an upcoming premiere. A finished
    livestream still flagged ``post_live`` is only deferred while its VOD isn't
    downloadable yet — yt-dlp can keep that flag set for hours/days after a
    complete VOD exists, so we allow it once real formats are available.

    Args:
        info: yt-dlp info dict from extract_info

    Returns:
        Tuple of (is_ready, reason). If not ready, reason explains why.
    """
    if not info:
        return False, 'No video info available'

    if info.get('is_live'):
        return False, 'Video is currently live'

    live_status = info.get('live_status')
    if live_status == 'is_live':
        return False, 'Video is currently live'
    if live_status == 'is_upcoming':
        return False, 'Video is an upcoming premiere'
    if live_status == 'post_live':
        # yt-dlp can keep a finished livestream flagged 'post_live' for hours or
        # even days after a complete, downloadable VOD already exists. Treat it as
        # ready once real formats are available; only defer during the brief window
        # right after a stream ends, before any VOD formats have been generated.
        if _has_downloadable_formats(info):
            return True, ''
        return False, 'Video is still processing after live stream'

    return True, ''


def build_not_ready_message(
    reason: str,
    release_timestamp: datetime | None,
    has_subscription: bool,
) -> str:
    """Build the user-facing status message for an unreleased (NOT_READY) video.

    Args:
        reason: Why the video isn't ready (from is_video_ready_for_download)
        release_timestamp: Scheduled release time if known (naive or tz-aware)
        has_subscription: Whether the job came from a subscription (auto-rechecked)

    Returns:
        Message like 'Video is an upcoming premiere. Premieres 2026-07-08 15:00.
        Will retry when the subscription checks again.'
    """
    parts = [f'{reason}.']

    if release_timestamp is not None:
        now = datetime.now(release_timestamp.tzinfo) if release_timestamp.tzinfo else datetime.now()
        if release_timestamp > now:
            parts.append(f'Premieres {release_timestamp:%Y-%m-%d %H:%M}.')

    if has_subscription:
        parts.append('Will retry when the subscription checks again.')
    else:
        parts.append('Try again when the video is available.')

    return ' '.join(parts)


def extract_entries_from_info(info: dict) -> list[dict]:
    """Extract video entries with full available metadata from yt-dlp info dict.

    Returns list of dicts with keys: url, title, duration, upload_date,
    release_timestamp, channel (all optional except url). Entry URLs are
    canonicalized, so a Shorts entry (which yt-dlp yields as /shorts/<id>) carries
    the same watch?v=<id> identity that MediaDetails is keyed on.
    """
    if not info:
        return []

    entries = info.get('entries', [])
    if not entries:
        return []

    def _extract_entry(entry: dict) -> dict | None:
        url = entry.get('url') or entry.get('webpage_url')
        if not url:
            return None
        return {
            'url': normalize_video_url(url),
            'title': entry.get('title', 'Unknown'),
            'duration': entry.get('duration'),
            'upload_date': entry.get('upload_date'),
            'release_timestamp': entry.get('release_timestamp'),
            'channel': get_channel_from_info(entry),
        }

    results = []

    # Handle flat entries (direct video list)
    if isinstance(entries[0], dict) and 'url' in entries[0]:
        for entry in entries:
            extracted = _extract_entry(entry)
            if extracted:
                results.append(extracted)

    # Handle nested entries
    elif isinstance(entries[0], dict) and 'entries' in entries[0]:
        for entry in entries:
            for video in entry.get('entries', []):
                extracted = _extract_entry(video)
                if extracted:
                    results.append(extracted)

    return results
