import hashlib

from logger import logger
from models import MediaDetails, TaskStatus
from repositories import media_details as md_repo
from schemas import DownloadJobDTO
from serializers import serialize_download_job
from ytdlp.info import get_channel_from_info, get_url_info
from ytdlp.urls import normalize_video_url


def is_repeat_download(md: MediaDetails) -> bool:
    """
    Check if this media has already been downloaded (COMPLETE or SKIPPED status).

    Args:
        md: MediaDetails to check

    Returns:
        True if already downloaded, False otherwise
    """
    existing = md_repo.sync_get_media_details_by_url_and_media_type(
        normalize_video_url(md.url),
        md.media_type.value if md.media_type else None,
    )
    if existing and existing.status in [TaskStatus.COMPLETE, TaskStatus.SKIPPED]:
        logger.debug(f'{existing} already exists with status {existing.status}. Skipping.')
        return True
    return False


def get_playlist_name(info: dict, url: str) -> str:
    """Extract playlist name from yt-dlp info, falling back to a URL-based hash."""
    name = info.get('title') or info.get('playlist_title')
    if not name:
        url_hash = hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()[:8]
        name = f'Playlist_{url_hash}'
    return name


def populate_playlist_jobs(dl_job: dict, url: str) -> list[dict]:
    """
    Expand playlist into individual video jobs.

    Args:
        dl_job: Base download job dict
        url: Playlist URL

    Returns:
        List of fully populated DownloadJobDTO dicts (one per video)
    """
    from serializers import deserialize_subscription

    info = get_url_info(url)
    if not info:
        logger.warning(f'Playlist extraction returned no info for {url}; skipping expansion')
        return []

    # Used for subdirectory organization
    playlist_name = get_playlist_name(info, url)

    complete_jobs = []

    subscription_dto = None
    if dl_job.get('subscription'):
        subscription_dto = deserialize_subscription(dl_job['subscription'])

    for _index, entry in enumerate(info.get('entries', [])):
        if not entry:  # Skip None entries
            continue

        entry_url = entry.get('url') or entry.get('webpage_url')
        if not entry_url:
            continue

        complete_job_dto = DownloadJobDTO(
            url=normalize_video_url(entry_url),
            audio_only=dl_job['audio_only'],
            media_type=dl_job['media_type'],
            job_type=dl_job['job_type'],
            # Populated from yt-dlp
            channel=get_channel_from_info(entry) or 'Unknown',
            title=entry.get('title', 'Unknown'),
            overwrite=dl_job['overwrite'],
            download_playlist=False,  # Don't re-expand
            generate_transcript=dl_job['generate_transcript'],
            download_quality=dl_job.get('download_quality', 'BEST'),
            audio_quality=dl_job.get('audio_quality', 'BEST'),
            subscription=subscription_dto,
            playlist_name=playlist_name,
            source_playlist_url=url,  # Pass YouTube playlist URL for auto-creating app playlists
            user_id=dl_job.get('user_id'),
        )

        complete_jobs.append(serialize_download_job(complete_job_dto))

    return complete_jobs
