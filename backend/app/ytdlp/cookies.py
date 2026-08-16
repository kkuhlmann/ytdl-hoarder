"""One decision point for whether a yt-dlp run gets cookies, plus a private copy of the
cookie file for it to write to."""

import contextlib
import os
import shutil
import tempfile
from collections.abc import Iterator

from logger import logger
from models import COOKIE_FILE_PATH, CookiesMode
from repositories import settings as settings_repo


def _cookies_wanted(cookies_mode: str, *, is_retry: bool, metadata_only: bool) -> bool:
    if cookies_mode == CookiesMode.ALWAYS.value:
        return True
    # Metadata extraction has no attempt counter, so RETRIES_ONLY can only mean never.
    if metadata_only:
        return False
    return cookies_mode == CookiesMode.RETRIES_ONLY.value and is_retry


@contextlib.contextmanager
def cookie_session(*, is_retry: bool = False, metadata_only: bool = False) -> Iterator[str | None]:
    """Yield a disposable copy of the cookie file, or None when cookies are off.

    yt-dlp truncates and rewrites `cookiefile` on every close, with no locking, and
    lanes run concurrently in one process. Pointing several runs at the uploaded file
    lets a job that started earlier overwrite a rotated session cookie a later job
    already persisted, and leaves a half-written file if a run is killed mid-close.
    A per-run copy makes the uploaded file read-only in practice; the rotated values
    it discards are worth less than the ones a clobber would destroy.
    """
    cookies_mode = settings_repo.sync_get_settings().cookies_mode
    if not _cookies_wanted(cookies_mode, is_retry=is_retry, metadata_only=metadata_only):
        yield None
        return

    if not os.path.isfile(COOKIE_FILE_PATH):
        yield None
        return

    fd, copy_path = tempfile.mkstemp(prefix='ytdl-cookies-', suffix='.txt')
    os.close(fd)
    try:
        shutil.copyfile(COOKIE_FILE_PATH, copy_path)
        logger.info(f'Using cookie file (mode={cookies_mode}, metadata_only={metadata_only})')
        yield copy_path
    finally:
        with contextlib.suppress(OSError):
            os.unlink(copy_path)
