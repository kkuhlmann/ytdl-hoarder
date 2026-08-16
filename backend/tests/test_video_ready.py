"""Unit tests for is_video_ready_for_download (ytdlp.info).

A finished livestream can stay flagged live_status='post_live' in yt-dlp for
hours/days after a complete, downloadable VOD already exists. The readiness
check must NOT defer such videos once real formats are available — it should
only defer while the VOD genuinely isn't downloadable yet (live / upcoming /
post-live with no formats).
"""

import pytest
from yt_dlp.utils import DownloadError

from ytdlp.info import (
    EXTRACTION_TRANSIENT,
    EXTRACTION_UNAVAILABLE,
    _has_downloadable_formats,
    classify_extraction_error,
    is_video_ready_for_download,
)

# A realistic pair of real DASH formats (audio-only + 1080p video-only), as a
# finished VOD exposes them.
_REAL_FORMATS = [
    {'format_id': '140', 'vcodec': 'none', 'acodec': 'mp4a.40.2'},
    {'format_id': '137', 'vcodec': 'avc1.4d4028', 'acodec': 'none'},
]

_NOT_READY_POST_LIVE = (False, 'Video is still processing after live stream')


def test_post_live_with_formats_is_ready():
    """The bug fix: a finished stream still flagged post_live but with a full
    format ladder must be treated as downloadable."""
    info = {'live_status': 'post_live', 'is_live': False, 'formats': _REAL_FORMATS}
    assert is_video_ready_for_download(info) == (True, '')


def test_post_live_without_formats_is_deferred():
    info = {'live_status': 'post_live', 'is_live': False, 'formats': []}
    assert is_video_ready_for_download(info) == _NOT_READY_POST_LIVE


def test_post_live_missing_formats_key_is_deferred():
    info = {'live_status': 'post_live', 'is_live': False}
    assert is_video_ready_for_download(info) == _NOT_READY_POST_LIVE


def test_post_live_with_only_bogus_formats_is_deferred():
    """Formats present but neither audio nor video (e.g. storyboard) don't count."""
    info = {
        'live_status': 'post_live',
        'is_live': False,
        'formats': [{'format_id': 'sb0', 'vcodec': 'none', 'acodec': 'none'}],
    }
    assert is_video_ready_for_download(info) == _NOT_READY_POST_LIVE


def test_is_live_boolean_flag_is_deferred():
    info = {'is_live': True, 'formats': _REAL_FORMATS}
    assert is_video_ready_for_download(info) == (False, 'Video is currently live')


def test_live_status_is_live_is_deferred():
    info = {'live_status': 'is_live', 'is_live': False}
    assert is_video_ready_for_download(info) == (False, 'Video is currently live')


def test_is_upcoming_is_deferred():
    info = {'live_status': 'is_upcoming', 'is_live': False}
    assert is_video_ready_for_download(info) == (False, 'Video is an upcoming premiere')


def test_was_live_is_ready():
    info = {'live_status': 'was_live', 'is_live': False, 'formats': _REAL_FORMATS}
    assert is_video_ready_for_download(info) == (True, '')


def test_normal_video_is_ready():
    info = {'live_status': 'not_live', 'is_live': False, 'formats': _REAL_FORMATS}
    assert is_video_ready_for_download(info) == (True, '')


def test_no_live_status_is_ready():
    info = {'title': 'Regular video', 'formats': _REAL_FORMATS}
    assert is_video_ready_for_download(info) == (True, '')


def test_empty_or_missing_info_is_not_ready():
    assert is_video_ready_for_download({}) == (False, 'No video info available')
    assert is_video_ready_for_download(None) == (False, 'No video info available')


def test_has_downloadable_formats_helper():
    assert _has_downloadable_formats({'formats': _REAL_FORMATS}) is True
    assert _has_downloadable_formats({'formats': []}) is False
    assert _has_downloadable_formats({}) is False
    assert _has_downloadable_formats({'formats': [{'vcodec': 'none', 'acodec': 'none'}]}) is False


class TestClassifyExtractionError:
    """Deciding how long to park an unresolvable URL.

    get_url_info swallows every extractor failure into a None, so a rate-limit block
    and a private video are indistinguishable at the call site. Callers back off for
    days on 'unavailable', which makes the false-positive direction the expensive one.
    """

    @pytest.mark.parametrize(
        'message',
        [
            'ERROR: [youtube] abc123: Private video. Sign in if you have been granted access',
            'ERROR: [youtube] abc123: Video unavailable',
            'ERROR: [youtube] abc123: Join this channel to get access to members-only content',
            'ERROR: [youtube] abc123: The uploader has not made this video available in your country',
            'ERROR: [youtube] abc123: Sign in to confirm your age. This video may be inappropriate',
            'ERROR: [youtube] abc123: This video has been removed by the uploader',
            'ERROR: [youtube] abc123: This account has been terminated',
        ],
    )
    def test_permanent_failures_are_unavailable(self, message):
        assert classify_extraction_error(DownloadError(message)) == EXTRACTION_UNAVAILABLE

    @pytest.mark.parametrize(
        'message',
        [
            'ERROR: [youtube] abc123: HTTP Error 429: Too Many Requests',
            "ERROR: [youtube] abc123: Sign in to confirm you're not a bot",
            'ERROR: [youtube] abc123: Unable to download webpage: The read operation timed out',
            'ERROR: [youtube] abc123: HTTP Error 403: Forbidden',
            'ERROR: [youtube] abc123: Requested format is not available',
            'ERROR: unable to connect to proxy',
            'something nobody has seen before',
        ],
    )
    def test_recoverable_and_unknown_failures_are_transient(self, message):
        """The load-bearing direction: an unrecognized error must never inherit the
        multi-day backoff, or one 403 burst parks a whole channel for a week."""
        assert classify_extraction_error(DownloadError(message)) == EXTRACTION_TRANSIENT

    def test_bot_check_is_not_confused_with_the_age_gate(self):
        """'Sign in to confirm you're not a bot' vs 'Sign in to confirm your age' —
        near-identical prefixes with opposite meanings."""
        bot = DownloadError("Sign in to confirm you're not a bot")
        age = DownloadError('Sign in to confirm your age')

        assert classify_extraction_error(bot) == EXTRACTION_TRANSIENT
        assert classify_extraction_error(age) == EXTRACTION_UNAVAILABLE
