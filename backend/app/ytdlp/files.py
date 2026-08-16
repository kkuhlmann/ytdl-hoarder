import os

from logger import logger

VIDEO_EXTENSIONS = ('mp4', 'mkv', 'webm', 'avi', 'mov', 'flv')
AUDIO_EXTENSIONS = ('m4a', 'mp3', 'opus', 'wav', 'flac', 'ogg', 'aac')


def find_existing_file(outtmpl: str, audio_only: bool = False) -> str | None:
    """
    Check if a file already exists matching the outtmpl pattern.

    Args:
        outtmpl: The output template path with %(ext)s placeholder
        audio_only: If True, only check audio extensions; otherwise check video extensions

    Returns:
        The full file path if found, None otherwise
    """
    if '%(ext)s' not in outtmpl:
        if os.path.isfile(outtmpl):
            return outtmpl
        return None

    extensions = AUDIO_EXTENSIONS if audio_only else VIDEO_EXTENSIONS
    base_path = outtmpl.replace('.%(ext)s', '')

    for ext in extensions:
        file_path = f'{base_path}.{ext}'
        if os.path.isfile(file_path):
            logger.info(f'Found existing file: {file_path}')
            return file_path

    return None


def download_thumbnail(thumbnail_url: str, media_file_path: str) -> str | None:
    """Download thumbnail and save as a sidecar file next to the media file.

    Uses the same sidecar convention as .peaks.json.gz — the thumbnail is saved as
    {base_path}.thumb.jpg alongside the media file.

    Args:
        thumbnail_url: Remote URL of the thumbnail image
        media_file_path: Path to the downloaded media file (used to derive sidecar path)

    Returns:
        Local path to the saved thumbnail, or None on any failure (thumbnails are non-critical)
    """
    import httpx

    base_path = os.path.splitext(media_file_path)[0]
    thumb_path = base_path + '.thumb.jpg'

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(thumbnail_url)
            resp.raise_for_status()

        with open(thumb_path, 'wb') as f:
            f.write(resp.content)

        logger.info(f'Downloaded thumbnail to {thumb_path}')
    except Exception as e:  # noqa: BLE001 — thumbnails are optional; failure must not fail the download
        logger.warning(f'Failed to download thumbnail from {thumbnail_url}: {e}')
        # Clean up partial file on error
        try:
            if os.path.isfile(thumb_path):
                os.remove(thumb_path)
        except OSError:
            pass
        return None
    else:
        return thumb_path
