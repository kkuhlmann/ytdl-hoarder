"""cookie_session is the one place that decides whether a yt-dlp run gets cookies,
and it hands out a private copy so concurrent runs cannot clobber the uploaded file."""

import os
from pathlib import Path

import pytest

from models import AppSettings, CookiesMode
from ytdlp.cookies import cookie_session


@pytest.fixture
def cookie_env(monkeypatch, tmp_path):
    master = tmp_path / 'cookies.txt'
    master.write_text('# Netscape HTTP Cookie File\n\nORIGINAL\n')
    monkeypatch.setattr('ytdlp.cookies.COOKIE_FILE_PATH', str(master))

    def configure(mode: str, *, file_exists: bool = True):
        if not file_exists:
            master.unlink()
        monkeypatch.setattr(
            'ytdlp.cookies.settings_repo.sync_get_settings',
            lambda: AppSettings(cookies_mode=mode),
        )
        return master

    return configure


def test_never_mode_yields_none(cookie_env):
    cookie_env(CookiesMode.NEVER.value)
    with cookie_session(is_retry=True) as path:
        assert path is None


def test_missing_file_yields_none(cookie_env):
    cookie_env(CookiesMode.ALWAYS.value, file_exists=False)
    with cookie_session() as path:
        assert path is None


def test_retries_only_skips_the_first_attempt(cookie_env):
    cookie_env(CookiesMode.RETRIES_ONLY.value)
    with cookie_session(is_retry=False) as path:
        assert path is None
    with cookie_session(is_retry=True) as path:
        assert path is not None


def test_metadata_only_requires_always_mode(cookie_env):
    """Metadata extraction has no retry counter, so RETRIES_ONLY means never for it."""
    cookie_env(CookiesMode.RETRIES_ONLY.value)
    with cookie_session(is_retry=True, metadata_only=True) as path:
        assert path is None
    cookie_env(CookiesMode.ALWAYS.value)
    with cookie_session(metadata_only=True) as path:
        assert path is not None


def test_yields_a_copy_not_the_master(cookie_env):
    master = cookie_env(CookiesMode.ALWAYS.value)
    with cookie_session() as path:
        assert path != str(master)
        assert Path(path).read_text() == master.read_text()


def test_the_master_survives_a_run_that_rewrites_its_copy(cookie_env):
    """yt-dlp truncates and rewrites cookiefile on close; the uploaded file must not
    be what it truncates."""
    master = cookie_env(CookiesMode.ALWAYS.value)
    with cookie_session() as path:
        Path(path).write_text('CLOBBERED BY YT-DLP\n')
    assert 'ORIGINAL' in master.read_text()


def test_the_copy_is_deleted_on_exit(cookie_env):
    cookie_env(CookiesMode.ALWAYS.value)
    with cookie_session() as path:
        leaked = path
    assert not os.path.exists(leaked)


def test_the_copy_is_deleted_when_the_body_raises(cookie_env):
    cookie_env(CookiesMode.ALWAYS.value)
    leaked = None
    with pytest.raises(RuntimeError), cookie_session() as path:
        leaked = path
        msg = 'download blew up'
        raise RuntimeError(msg)
    assert not os.path.exists(leaked)


def test_concurrent_sessions_get_distinct_copies(cookie_env):
    cookie_env(CookiesMode.ALWAYS.value)
    with cookie_session() as first, cookie_session() as second:
        assert first != second
