"""The display codes behind a RETRY row's `<code> (3/20): Retries in 4m` message."""

import pytest

from orchestrator.error_codes import ERROR_CODE_MAX_LENGTH, classify_error


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ('ERROR: unable to download video data: HTTP Error 403: Forbidden', 'HTTP 403'),
        ('Unable to download webpage: HTTP Error 429: Too Many Requests', 'HTTP 429'),
        ('HTTP Error 404: Not Found', 'HTTP 404'),
        ("Sign in to confirm you're not a bot. Use --cookies", 'BOT_CHECK'),
        ('Signature solving failed: Failed to load JS runtime', 'SIGNATURE'),
        ('nsig extraction failed', 'SIGNATURE'),
        ('Requested format is not available', 'FORMAT'),
        ('The uploader has not made this video available in your country', 'GEO_BLOCKED'),
        ('Private video. Sign in if you have been granted access', 'PRIVATE'),
        ('Join this channel to get access to members-only content', 'PRIVATE'),
        ('Sign in to confirm your age', 'AGE_RESTRICTED'),
        ('Video unavailable. This video has been removed by the uploader', 'REMOVED'),
        ('OSError: [Errno 28] No space left on device', 'DISK_FULL'),
        ('Connection reset by peer', 'NETWORK'),
        ('Temporary failure in name resolution', 'NETWORK'),
        ('ffmpeg exited with code 1', 'FFMPEG'),
    ],
)
def test_classifies_known_failures(message, expected):
    assert classify_error(RuntimeError(message)) == expected


def test_specific_patterns_beat_the_http_status():
    """A bot check arrives as a 429; the row should say why, not just the number."""
    exc = RuntimeError("HTTP Error 429: Sign in to confirm you're not a bot")
    assert classify_error(exc) == 'BOT_CHECK'


def test_falls_back_to_the_exception_class():
    assert classify_error(ValueError('something nobody has seen before')) == 'ValueError'


def test_no_exception_means_no_code():
    assert classify_error(None) is None


def test_fallback_is_length_capped():
    long_name = 'A' * 200
    exc_type = type(long_name, (Exception,), {})
    code = classify_error(exc_type('boom'))
    assert len(code) == ERROR_CODE_MAX_LENGTH
