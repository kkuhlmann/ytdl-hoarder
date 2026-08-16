"""Retry policies: exponential backoff + the transient-DB retry decorator."""

import pytest
from sqlalchemy.exc import OperationalError

from orchestrator.retry import (
    CLIP_RETRY_POLICY,
    DOWNLOAD_RETRY_POLICY,
    TRANSCRIPT_RETRY_POLICY,
    RetryPolicy,
    retry_transient_db,
)


def test_download_policy_backoff():
    # base 300s, doubling, capped at 8h, 20 retries
    assert DOWNLOAD_RETRY_POLICY.max_retries == 20
    assert DOWNLOAD_RETRY_POLICY.backoff(1) == 300
    assert DOWNLOAD_RETRY_POLICY.backoff(2) == 600
    assert DOWNLOAD_RETRY_POLICY.backoff(3) == 1200
    assert DOWNLOAD_RETRY_POLICY.backoff(10) == 8 * 3600, 'capped at 8h'
    assert DOWNLOAD_RETRY_POLICY.backoff(20) == 8 * 3600


def test_transcript_policy_backoff():
    # base 30s, doubling, capped at 30min, 5 retries
    assert TRANSCRIPT_RETRY_POLICY.max_retries == 5
    assert TRANSCRIPT_RETRY_POLICY.backoff(1) == 30
    assert TRANSCRIPT_RETRY_POLICY.backoff(5) == 480
    assert TRANSCRIPT_RETRY_POLICY.backoff(7) == 30 * 60, 'capped at 30min'


def test_clip_policy_backoff():
    # base 30s, doubling, capped at 5min, 3 retries
    assert CLIP_RETRY_POLICY.max_retries == 3
    assert CLIP_RETRY_POLICY.backoff(1) == 30
    assert CLIP_RETRY_POLICY.backoff(4) == 240
    assert CLIP_RETRY_POLICY.backoff(5) == 300, 'capped at 5min'


def test_compute_delay_full_jitter_bounds():
    policy = RetryPolicy(base_delay=100, max_delay=1000, max_retries=5, jitter=True)
    for attempt in (1, 2, 3):
        for _ in range(50):
            delay = policy.compute_delay(attempt)
            assert 0 <= delay <= policy.backoff(attempt)


def test_compute_delay_without_jitter_is_exact():
    policy = RetryPolicy(base_delay=100, max_delay=1000, max_retries=5, jitter=False)
    assert policy.compute_delay(1) == 100
    assert policy.compute_delay(2) == 200
    assert policy.compute_delay(5) == 1000


def _transient_error():
    return OperationalError('SELECT 1', None, Exception('EAI_AGAIN'))


def test_retry_transient_db_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr('orchestrator.retry.time.sleep', lambda s: None)
    attempts = []

    @retry_transient_db
    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise _transient_error()
        return 'ok'

    assert flaky() == 'ok'
    assert len(attempts) == 3


def test_retry_transient_db_gives_up_after_max(monkeypatch):
    monkeypatch.setattr('orchestrator.retry.time.sleep', lambda s: None)
    attempts = []

    @retry_transient_db
    def always_broken():
        attempts.append(1)
        raise _transient_error()

    with pytest.raises(OperationalError):
        always_broken()
    assert len(attempts) == 6, '1 initial + 5 retries'


def test_retry_transient_db_does_not_catch_other_errors(monkeypatch):
    monkeypatch.setattr('orchestrator.retry.time.sleep', lambda s: None)
    attempts = []

    @retry_transient_db
    def broken():
        attempts.append(1)
        msg = 'a real bug'
        raise ValueError(msg)

    with pytest.raises(ValueError):
        broken()
    assert len(attempts) == 1
