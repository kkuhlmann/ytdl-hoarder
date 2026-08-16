"""Rate limiting on the unauthenticated auth endpoints.

The endpoint tests deliberately assert on *response equality* rather than only on the
429, because the anti-enumeration guarantee is the thing most easily broken by adding a
limiter: the moment the budget depends on the submitted username, identical bodies stop
being enough to hide which accounts exist.
"""

import pytest
from fastapi.testclient import TestClient

import rate_limit
import routers.auth as auth_router
from main import app
from rate_limit import MAX_TRACKED_CLIENTS, SlidingWindowLimiter


class TestSlidingWindowLimiter:
    def test_allows_up_to_the_limit(self):
        limiter = SlidingWindowLimiter(limit=3, window_seconds=60)

        assert [limiter.retry_after('ip', now=0) for _ in range(3)] == [None, None, None]

    def test_blocks_past_the_limit(self):
        limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            limiter.retry_after('ip', now=0)

        assert limiter.retry_after('ip', now=0) == pytest.approx(60)

    def test_window_slides_rather_than_resetting_on_a_fixed_boundary(self):
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
        limiter.retry_after('ip', now=0)
        limiter.retry_after('ip', now=30)

        assert limiter.retry_after('ip', now=59) is not None
        # Only the hit at t=0 has aged out, so exactly one slot frees up.
        assert limiter.retry_after('ip', now=61) is None
        assert limiter.retry_after('ip', now=61) is not None

    def test_rejected_calls_do_not_extend_the_block(self):
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.retry_after('ip', now=0)
        for t in range(1, 60):
            limiter.retry_after('ip', now=t)

        assert limiter.retry_after('ip', now=61) is None

    def test_keys_are_independent(self):
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.retry_after('10.0.0.1', now=0)

        assert limiter.retry_after('10.0.0.2', now=0) is None

    def test_retry_after_shrinks_as_the_window_ages(self):
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.retry_after('ip', now=0)

        assert limiter.retry_after('ip', now=10) == pytest.approx(50)
        assert limiter.retry_after('ip', now=50) == pytest.approx(10)

    def test_idle_keys_are_dropped(self):
        limiter = SlidingWindowLimiter(limit=5, window_seconds=60)
        limiter.retry_after('stale', now=0)
        limiter.retry_after('fresh', now=100)

        assert 'stale' not in limiter._hits

    def test_table_stays_bounded_against_address_rotation(self):
        limiter = SlidingWindowLimiter(limit=5, window_seconds=3600)
        for i in range(MAX_TRACKED_CLIENTS + 500):
            limiter.retry_after(f'10.0.{i // 256}.{i % 256}', now=0)

        assert len(limiter._hits) <= MAX_TRACKED_CLIENTS

    def test_eviction_drops_the_least_recently_used_not_the_active_one(self):
        limiter = SlidingWindowLimiter(limit=5, window_seconds=3600)
        limiter.retry_after('attacker', now=0)
        for i in range(MAX_TRACKED_CLIENTS + 10):
            limiter.retry_after(f'noise-{i}', now=1)
            limiter.retry_after('attacker', now=1)

        # Rotating addresses must not flush the persistent caller's own counter.
        assert 'attacker' in limiter._hits


@pytest.fixture
def client(test_database):
    return TestClient(app)


def exhaust(client, path, payload, limiter):
    """Spend the whole budget for `limiter`, asserting nothing is blocked yet."""
    for _ in range(limiter.limit):
        assert client.post(path, json=payload).status_code != 429


class TestLoginRateLimit:
    def test_rapid_failed_logins_start_returning_429(self, client):
        payload = {'username': 'nobody', 'password': 'wrong-password'}
        exhaust(client, '/auth/login', payload, rate_limit.LOGIN_LIMITER)

        resp = client.post('/auth/login', json=payload)

        assert resp.status_code == 429
        assert int(resp.headers['retry-after']) > 0

    def test_normal_use_is_not_limited(self, client):
        client.post('/auth/register', json={'username': 'alice', 'password': 'testpass123'})

        for _ in range(3):
            assert (
                client.post(
                    '/auth/login', json={'username': 'alice', 'password': 'wrong'}
                ).status_code
                == 401
            )
        resp = client.post('/auth/login', json={'username': 'alice', 'password': 'testpass123'})

        assert resp.status_code == 200

    def test_a_valid_password_does_not_bypass_the_limit(self, client):
        client.post('/auth/register', json={'username': 'alice', 'password': 'testpass123'})
        exhaust(
            client,
            '/auth/login',
            {'username': 'alice', 'password': 'wrong'},
            rate_limit.LOGIN_LIMITER,
        )

        resp = client.post('/auth/login', json={'username': 'alice', 'password': 'testpass123'})

        assert resp.status_code == 429

    def test_the_budget_is_charged_before_the_password_check(self, client, monkeypatch):
        """Blocked requests must not reach bcrypt — that cost is the DoS being closed."""
        client.post('/auth/register', json={'username': 'alice', 'password': 'testpass123'})
        exhaust(
            client,
            '/auth/login',
            {'username': 'alice', 'password': 'wrong'},
            rate_limit.LOGIN_LIMITER,
        )
        calls = []
        monkeypatch.setattr(auth_router, 'verify_password', lambda *args: calls.append(args))

        resp = client.post('/auth/login', json={'username': 'alice', 'password': 'x'})

        assert resp.status_code == 429
        assert calls == []


class TestRegisterRateLimit:
    def test_flooding_registrations_is_blocked(self, client):
        for i in range(rate_limit.REGISTER_LIMITER.limit):
            resp = client.post(
                '/auth/register', json={'username': f'user{i}', 'password': 'testpass123'}
            )
            assert resp.status_code != 429

        resp = client.post('/auth/register', json={'username': 'flood', 'password': 'testpass123'})

        assert resp.status_code == 429


class TestRecoveryRateLimit:
    def test_forgot_password_is_limited(self, client):
        exhaust(
            client, '/auth/forgot-password', {'username': 'nobody'}, rate_limit.RECOVERY_LIMITER
        )

        assert client.post('/auth/forgot-password', json={'username': 'nobody'}).status_code == 429

    def test_recovery_endpoints_share_one_budget(self, client):
        """Burning the budget guessing codes must also stop new codes being minted."""
        exhaust(
            client, '/auth/forgot-password', {'username': 'nobody'}, rate_limit.RECOVERY_LIMITER
        )

        resp = client.post('/auth/admin-recovery/request', json={'username': 'nobody'})

        assert resp.status_code == 429

    def test_admin_recovery_complete_is_limited(self, client):
        payload = {'username': 'admin', 'code': 'GUESS', 'new_password': 'testpass123'}
        exhaust(client, '/auth/admin-recovery/complete', payload, rate_limit.RECOVERY_LIMITER)

        assert client.post('/auth/admin-recovery/complete', json=payload).status_code == 429


class TestLimiterIsNotAUsernameOracle:
    """A per-username budget would answer "does this account exist" through 429 timing."""

    def test_forgot_password_spends_the_same_budget_for_real_and_unknown_users(self, client):
        client.post('/auth/register', json={'username': 'alice', 'password': 'testpass123'})
        limit = rate_limit.RECOVERY_LIMITER.limit

        # Half the budget on a real account, half on one that does not exist.
        for i in range(limit):
            username = 'alice' if i % 2 else f'ghost{i}'
            assert (
                client.post('/auth/forgot-password', json={'username': username}).status_code != 429
            )

        real = client.post('/auth/forgot-password', json={'username': 'alice'})
        unknown = client.post('/auth/forgot-password', json={'username': 'ghost'})

        assert real.status_code == unknown.status_code == 429
        assert real.json() == unknown.json()

    def test_a_blocked_response_is_identical_for_admin_and_unknown_usernames(self, client):
        client.post('/auth/register', json={'username': 'admin', 'password': 'testpass123'})
        exhaust(
            client, '/auth/admin-recovery/request', {'username': 'zzz'}, rate_limit.RECOVERY_LIMITER
        )

        admin = client.post('/auth/admin-recovery/request', json={'username': 'admin'})
        unknown = client.post('/auth/admin-recovery/request', json={'username': 'nobody'})

        assert admin.status_code == unknown.status_code == 429
        assert admin.json() == unknown.json()

    def test_login_blocking_does_not_depend_on_the_username(self, client):
        client.post('/auth/register', json={'username': 'alice', 'password': 'testpass123'})
        exhaust(
            client, '/auth/login', {'username': 'zzz', 'password': 'x'}, rate_limit.LOGIN_LIMITER
        )

        real = client.post('/auth/login', json={'username': 'alice', 'password': 'x'})
        unknown = client.post('/auth/login', json={'username': 'nobody', 'password': 'x'})

        assert real.status_code == unknown.status_code == 429
        assert real.json() == unknown.json()
