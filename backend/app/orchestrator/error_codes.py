"""Short, display-only error codes for the Tasks UI.

A retrying task's row shows `<code> (3/20): Retries in 4m` instead of the raw
exception, so the code has to be short, stable and scannable — the full text is
still on the row's status_message.

Deliberately NOT sharing patterns with ytdlp.info._UNAVAILABLE_ERROR_PATTERNS:
that list is the whitelist gating the *long* deferral ladder, where a false
positive parks a rate-limited channel for a week. This one only picks a label,
so it can grow freely; merging them would couple a cosmetic change to that.
"""

import re

# Longest code we will render. The class-name fallback is unbounded otherwise.
ERROR_CODE_MAX_LENGTH = 32

_HTTP_STATUS_PATTERN = re.compile(r'http error (\d{3})')

# Ordered: first match wins, so the specific patterns must precede the generic
# ones (a bot-check 429 should read BOT_CHECK, not HTTP 429).
_ERROR_CODE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # "not a bot", not "sign in to confirm" — the age-restriction message opens the
    # same way and would otherwise be labelled a bot check.
    ('BOT_CHECK', ('not a bot',)),
    ('SIGNATURE', ('signature solving failed', 'nsig extraction failed')),
    ('FORMAT', ('requested format is not available',)),
    ('GEO_BLOCKED', ('available in your country', 'blocked it in your country')),
    ('PRIVATE', ('private video', 'members-only', 'available to members')),
    ('AGE_RESTRICTED', ('confirm your age', 'age-restricted')),
    ('REMOVED', ('has been removed', 'video unavailable', 'has been terminated')),
    ('DISK_FULL', ('no space left on device',)),
    (
        'NETWORK',
        (
            'connection reset',
            'timed out',
            'temporary failure in name resolution',
            'unable to connect',
        ),
    ),
    ('FFMPEG', ('ffmpeg', 'ffprobe')),
)


def classify_error(exc: BaseException | None) -> str | None:
    """Pick a short code for an exception, or None when there is no exception."""
    if exc is None:
        return None

    message = str(exc).lower()

    for code, patterns in _ERROR_CODE_PATTERNS:
        if any(pattern in message for pattern in patterns):
            return code

    http_match = _HTTP_STATUS_PATTERN.search(message)
    if http_match:
        return f'HTTP {http_match.group(1)}'

    return type(exc).__name__[:ERROR_CODE_MAX_LENGTH]
