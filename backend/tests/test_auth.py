"""Tests for authentication: password hashing, JWT, register/login/logout/me endpoints."""

from fastapi.testclient import TestClient

from auth import create_jwt_token, decode_jwt_token, hash_password, verify_password

# --- Unit tests for auth utilities (no DB needed) ---


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = 'my-secret-password'
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_wrong_password(self):
        hashed = hash_password('correct-password')
        assert not verify_password('wrong-password', hashed)

    def test_different_hashes_for_same_password(self):
        """bcrypt uses random salt, so two hashes of the same password differ."""
        h1 = hash_password('same-password')
        h2 = hash_password('same-password')
        assert h1 != h2
        # But both verify correctly
        assert verify_password('same-password', h1)
        assert verify_password('same-password', h2)


class TestJWT:
    def test_create_and_decode(self):
        token = create_jwt_token(user_id=42, username='alice', is_admin=True)
        payload = decode_jwt_token(token)
        assert payload is not None
        assert payload['user_id'] == 42
        assert payload['username'] == 'alice'
        assert payload['is_admin'] is True
        assert 'exp' in payload

    def test_invalid_token(self):
        assert decode_jwt_token('not-a-valid-token') is None

    def test_tampered_token(self):
        token = create_jwt_token(user_id=1, username='bob', is_admin=False)
        # Tamper with the token
        tampered = token[:-5] + 'XXXXX'
        assert decode_jwt_token(tampered) is None


# --- Integration tests with DB ---


class TestSetupStatus:
    def test_needs_setup_when_no_users(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.get('/auth/setup-status')
        assert resp.status_code == 200
        assert resp.json()['needs_setup'] is True

    def test_no_setup_after_user_created(self, test_database):
        from main import app

        client = TestClient(app)
        # Register first user
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        resp = client.get('/auth/setup-status')
        assert resp.status_code == 200
        assert resp.json()['needs_setup'] is False


class TestRegister:
    def test_first_user_is_admin_and_approved(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.post('/auth/register', json={'username': 'firstuser', 'password': 'pass123'})
        assert resp.status_code == 201
        data = resp.json()
        assert data['username'] == 'firstuser'
        assert data['is_admin'] is True
        assert data['is_approved'] is True

    def test_first_user_gets_cookie(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.post('/auth/register', json={'username': 'firstuser', 'password': 'pass123'})
        assert resp.status_code == 201
        assert 'auth_token' in resp.cookies

    def test_second_user_not_admin(self, test_database):
        from main import app

        client = TestClient(app)
        # First user
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        # Second user
        resp = client.post('/auth/register', json={'username': 'normaluser', 'password': 'pass123'})
        assert resp.status_code == 201
        data = resp.json()
        assert data['is_admin'] is False
        assert data['is_approved'] is False

    def test_second_user_no_cookie(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        resp = client.post('/auth/register', json={'username': 'normaluser', 'password': 'pass123'})
        assert resp.status_code == 201
        assert 'auth_token' not in resp.cookies

    def test_duplicate_username(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        resp = client.post('/auth/register', json={'username': 'admin', 'password': 'other123'})
        assert resp.status_code == 409

    def test_short_username(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.post('/auth/register', json={'username': 'ab', 'password': 'pass123'})
        assert resp.status_code == 400

    def test_short_password(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.post('/auth/register', json={'username': 'validuser', 'password': '12345'})
        assert resp.status_code == 400


class TestLogin:
    def test_login_success(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})
        resp = client.post('/auth/login', json={'username': 'alice', 'password': 'pass123'})
        assert resp.status_code == 200
        assert resp.json()['username'] == 'alice'
        assert 'auth_token' in resp.cookies

    def test_login_wrong_password(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})
        resp = client.post('/auth/login', json={'username': 'alice', 'password': 'wrong'})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.post('/auth/login', json={'username': 'ghost', 'password': 'pass123'})
        assert resp.status_code == 401


class TestLogout:
    def test_logout_clears_cookie(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})
        client.post('/auth/login', json={'username': 'alice', 'password': 'pass123'})
        resp = client.post('/auth/logout')
        assert resp.status_code == 200
        # Cookie should be cleared (set to empty or with max-age=0)
        assert resp.json()['status'] == 'ok'


class TestMe:
    def test_me_authenticated(self, test_database):
        from main import app

        client = TestClient(app)
        # Register (first user gets auto-logged-in cookie)
        reg_resp = client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})
        assert reg_resp.status_code == 201

        # Use the cookie from registration
        resp = client.get('/auth/me')
        assert resp.status_code == 200
        data = resp.json()
        assert data['username'] == 'alice'
        assert data['is_admin'] is True

    def test_me_unauthenticated(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.get('/auth/me')
        assert resp.status_code == 401


class TestShareableUsers:
    def test_shareable_users_returns_approved_only(self, test_database):
        from main import app

        client = TestClient(app)
        # Register first user (admin, auto-approved)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        # Register second user (not approved)
        client.post('/auth/register', json={'username': 'pending', 'password': 'pass123'})
        # Register third user, then approve them
        client.post('/auth/register', json={'username': 'approved', 'password': 'pass123'})

        # Get all users to find the third user's ID
        users_resp = client.get('/auth/users')
        third_user = next(u for u in users_resp.json() if u['username'] == 'approved')
        client.post(f'/auth/users/{third_user["id"]}/approve')

        # Shareable users should include admin and approved, but not pending
        resp = client.get('/auth/users/shareable')
        assert resp.status_code == 200
        usernames = (
            [u['username'] for u in resp.data]
            if hasattr(resp, 'data')
            else [u['username'] for u in resp.json()]
        )
        assert 'admin' in usernames
        assert 'approved' in usernames
        assert 'pending' not in usernames

    def test_shareable_users_only_returns_id_and_username(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})

        resp = client.get('/auth/users/shareable')
        assert resp.status_code == 200
        for user in resp.json():
            assert set(user.keys()) == {'id', 'username'}

    def test_shareable_users_unauthenticated(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.get('/auth/users/shareable')
        assert resp.status_code == 401


class TestUnauthenticatedAccess:
    """Verify that protected endpoints reject unauthenticated requests (Phase 3)."""

    def test_health_no_auth(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.get('/health')
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok'}

    def test_subscriptions_require_auth(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.get('/subscriptions')
        assert resp.status_code == 401


class TestApprovalEnforcement:
    """The admin-approval gate is enforced server-side, not just in the frontend.

    Unapproved users may authenticate (so the UI can show a "pending" screen) but
    cannot reach any data endpoint.
    """

    def _register_admin_and_pending(self):
        from main import app

        admin_client = TestClient(app)
        # First user is auto-admin + auto-approved.
        admin_client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        # Second user is pending approval.
        admin_client.post('/auth/register', json={'username': 'pending', 'password': 'pass123'})
        return admin_client

    def test_unapproved_login_succeeds(self, test_database):
        from main import app

        self._register_admin_and_pending()

        pending_client = TestClient(app)
        resp = pending_client.post(
            '/auth/login', json={'username': 'pending', 'password': 'pass123'}
        )
        # Login still issues a token so the frontend can render the pending screen.
        assert resp.status_code == 200
        assert resp.json()['is_approved'] is False
        assert 'auth_token' in pending_client.cookies

    def test_unapproved_blocked_from_data_endpoint(self, test_database):
        from main import app

        self._register_admin_and_pending()

        pending_client = TestClient(app)
        pending_client.post('/auth/login', json={'username': 'pending', 'password': 'pass123'})
        resp = pending_client.get('/subscriptions')
        assert resp.status_code == 403

    def test_unapproved_can_still_call_me(self, test_database):
        from main import app

        self._register_admin_and_pending()

        pending_client = TestClient(app)
        pending_client.post('/auth/login', json={'username': 'pending', 'password': 'pass123'})
        resp = pending_client.get('/auth/me')
        assert resp.status_code == 200
        assert resp.json()['is_approved'] is False

    def test_approved_user_can_access_data(self, test_database):
        from main import app

        admin_client = self._register_admin_and_pending()
        users = admin_client.get('/auth/users').json()
        pending = next(u for u in users if u['username'] == 'pending')
        admin_client.post(f'/auth/users/{pending["id"]}/approve')

        member_client = TestClient(app)
        member_client.post('/auth/login', json={'username': 'pending', 'password': 'pass123'})
        resp = member_client.get('/subscriptions')
        assert resp.status_code == 200

    def test_revoking_approval_takes_effect_immediately(self, test_database):
        from sqlalchemy import update

        from database import db
        from main import app
        from models import User

        admin_client = self._register_admin_and_pending()
        users = admin_client.get('/auth/users').json()
        pending = next(u for u in users if u['username'] == 'pending')
        admin_client.post(f'/auth/users/{pending["id"]}/approve')

        member_client = TestClient(app)
        member_client.post('/auth/login', json={'username': 'pending', 'password': 'pass123'})
        assert member_client.get('/subscriptions').status_code == 200

        # Revoke approval directly in the DB; the token is unchanged.
        session = db.get_sync_session()
        try:
            session.execute(
                update(User).where(User.username == 'pending').values(is_approved=False)
            )
            session.commit()
        finally:
            session.close()

        # Same cookie, but access is gone on the very next request.
        assert member_client.get('/subscriptions').status_code == 403


class TestIdentityRevalidation:
    """is_admin and account existence are resolved from the DB per request, not trusted
    from the (long-lived) token claims."""

    def test_demoted_admin_loses_admin_immediately(self, test_database):
        from sqlalchemy import update

        from database import db
        from main import app
        from models import User

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        # Admin-only endpoint works while the user is an admin.
        assert client.get('/auth/users').status_code == 200

        # Revoke admin in the DB; the JWT still asserts is_admin=True.
        session = db.get_sync_session()
        try:
            session.execute(update(User).where(User.username == 'admin').values(is_admin=False))
            session.commit()
        finally:
            session.close()

        # Same cookie, but admin power is gone immediately (not at token expiry).
        assert client.get('/auth/users').status_code == 403

    def test_deleted_user_token_rejected(self, test_database):
        from sqlalchemy import delete

        from database import db
        from main import app
        from models import User

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        assert client.get('/auth/me').status_code == 200

        # Delete the account; the token still decodes with a valid signature.
        session = db.get_sync_session()
        try:
            session.execute(delete(User).where(User.username == 'admin'))
            session.commit()
        finally:
            session.close()

        # No matching user row → treated as unauthenticated.
        assert client.get('/auth/me').status_code == 401
        assert client.get('/subscriptions').status_code == 401


# --- Password recovery ---


def _register_admin_and_member(app):
    """Register an auto-approved admin plus an approved member; return both clients."""
    admin_client = TestClient(app)
    admin_client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
    admin_client.post('/auth/register', json={'username': 'member', 'password': 'pass123'})

    users = admin_client.get('/auth/users').json()
    member = next(u for u in users if u['username'] == 'member')
    admin_client.post(f'/auth/users/{member["id"]}/approve')

    member_client = TestClient(app)
    member_client.post('/auth/login', json={'username': 'member', 'password': 'pass123'})
    return admin_client, member_client, member['id']


class TestChangePassword:
    def test_change_password_succeeds(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})

        resp = client.post(
            '/auth/me/change-password',
            json={'current_password': 'pass123', 'new_password': 'newpass456'},
        )
        assert resp.status_code == 200

        fresh = TestClient(app)
        assert (
            fresh.post(
                '/auth/login', json={'username': 'alice', 'password': 'newpass456'}
            ).status_code
            == 200
        )
        assert (
            fresh.post('/auth/login', json={'username': 'alice', 'password': 'pass123'}).status_code
            == 401
        )

    def test_caller_session_survives(self, test_database):
        """The cookie is re-issued, so changing your password doesn't sign you out."""
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})
        client.post(
            '/auth/me/change-password',
            json={'current_password': 'pass123', 'new_password': 'newpass456'},
        )
        assert client.get('/auth/me').status_code == 200

    def test_other_sessions_are_signed_out(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})

        other = TestClient(app)
        other.post('/auth/login', json={'username': 'alice', 'password': 'pass123'})
        assert other.get('/auth/me').status_code == 200

        client.post(
            '/auth/me/change-password',
            json={'current_password': 'pass123', 'new_password': 'newpass456'},
        )

        # Same cookie, but it was issued before the password changed.
        assert other.get('/auth/me').status_code == 401

    def test_wrong_current_password(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})
        resp = client.post(
            '/auth/me/change-password',
            json={'current_password': 'wrong', 'new_password': 'newpass456'},
        )
        assert resp.status_code == 401

    def test_short_new_password(self, test_database):
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'alice', 'password': 'pass123'})
        resp = client.post(
            '/auth/me/change-password',
            json={'current_password': 'pass123', 'new_password': '12345'},
        )
        assert resp.status_code == 400

    def test_unauthenticated(self, test_database):
        from main import app

        client = TestClient(app)
        resp = client.post(
            '/auth/me/change-password',
            json={'current_password': 'pass123', 'new_password': 'newpass456'},
        )
        assert resp.status_code == 401


class TestForgotPassword:
    def test_unknown_username_still_succeeds(self, test_database):
        """Never reveal which usernames are registered."""
        from main import app

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        resp = client.post('/auth/forgot-password', json={'username': 'ghost'})
        assert resp.status_code == 200

        users = client.get('/auth/users').json()
        assert all(u['password_reset_requested_at'] is None for u in users)

    def test_request_is_visible_to_admin(self, test_database):
        from main import app

        admin_client, _, member_id = _register_admin_and_member(app)

        assert (
            TestClient(app).post('/auth/forgot-password', json={'username': 'member'}).status_code
            == 200
        )

        users = admin_client.get('/auth/users').json()
        member = next(u for u in users if u['id'] == member_id)
        assert member['password_reset_requested_at'] is not None

    def test_repeat_request_keeps_original_timestamp(self, test_database):
        from main import app

        admin_client, _, member_id = _register_admin_and_member(app)
        anon = TestClient(app)

        anon.post('/auth/forgot-password', json={'username': 'member'})
        first = next(u for u in admin_client.get('/auth/users').json() if u['id'] == member_id)[
            'password_reset_requested_at'
        ]

        anon.post('/auth/forgot-password', json={'username': 'member'})
        second = next(u for u in admin_client.get('/auth/users').json() if u['id'] == member_id)[
            'password_reset_requested_at'
        ]

        assert first == second

    def test_admin_can_dismiss_request(self, test_database):
        from main import app

        admin_client, _, member_id = _register_admin_and_member(app)
        TestClient(app).post('/auth/forgot-password', json={'username': 'member'})

        resp = admin_client.delete(f'/auth/users/{member_id}/reset-request')
        assert resp.status_code == 204

        member = next(u for u in admin_client.get('/auth/users').json() if u['id'] == member_id)
        assert member['password_reset_requested_at'] is None


class TestAdminPasswordReset:
    def test_temp_password_works_and_forces_change(self, test_database):
        from main import app

        admin_client, _, member_id = _register_admin_and_member(app)
        TestClient(app).post('/auth/forgot-password', json={'username': 'member'})

        resp = admin_client.post(f'/auth/users/{member_id}/reset-password')
        assert resp.status_code == 200
        temp_password = resp.json()['temporary_password']

        # Resetting clears the outstanding request.
        member = next(u for u in admin_client.get('/auth/users').json() if u['id'] == member_id)
        assert member['password_reset_requested_at'] is None

        member_client = TestClient(app)
        login = member_client.post(
            '/auth/login', json={'username': 'member', 'password': temp_password}
        )
        assert login.status_code == 200
        assert login.json()['must_change_password'] is True

        # Authenticated, but walled off from data endpoints until they pick a password.
        assert member_client.get('/auth/me').status_code == 200
        assert member_client.get('/subscriptions').status_code == 403

        assert (
            member_client.post(
                '/auth/me/change-password',
                json={'current_password': temp_password, 'new_password': 'chosen123'},
            ).status_code
            == 200
        )
        assert member_client.get('/subscriptions').status_code == 200

        # The temporary password is dead once replaced.
        assert (
            TestClient(app)
            .post('/auth/login', json={'username': 'member', 'password': temp_password})
            .status_code
            == 401
        )

    def test_forced_change_cannot_be_opted_out_of(self, test_database):
        """A temporary password is always strictly temporary.

        The endpoint takes no body; a stale client sending the removed opt-out flag must
        not be able to hand someone a password they can keep.
        """
        from main import app

        admin_client, _, member_id = _register_admin_and_member(app)
        resp = admin_client.post(
            f'/auth/users/{member_id}/reset-password', json={'require_change': False}
        )
        temp_password = resp.json()['temporary_password']

        member_client = TestClient(app)
        member_client.post('/auth/login', json={'username': 'member', 'password': temp_password})
        assert member_client.get('/subscriptions').status_code == 403

    def test_reset_signs_out_existing_sessions(self, test_database):
        from main import app

        admin_client, member_client, member_id = _register_admin_and_member(app)
        assert member_client.get('/auth/me').status_code == 200

        admin_client.post(f'/auth/users/{member_id}/reset-password')
        assert member_client.get('/auth/me').status_code == 401

    def test_non_admin_cannot_reset(self, test_database):
        from main import app

        admin_client, member_client, _member_id = _register_admin_and_member(app)
        users = admin_client.get('/auth/users').json()
        admin_id = next(u for u in users if u['username'] == 'admin')['id']

        assert member_client.post(f'/auth/users/{admin_id}/reset-password').status_code == 403

    def test_admin_cannot_reset_self(self, test_database):
        from main import app

        admin_client, _, _ = _register_admin_and_member(app)
        admin_id = next(
            u for u in admin_client.get('/auth/users').json() if u['username'] == 'admin'
        )['id']

        resp = admin_client.post(f'/auth/users/{admin_id}/reset-password')
        assert resp.status_code == 400

    def test_reset_unknown_user(self, test_database):
        from main import app

        admin_client, _, _ = _register_admin_and_member(app)
        assert admin_client.post('/auth/users/99999/reset-password').status_code == 404


class TestAdminRecovery:
    @staticmethod
    def _code_from_file(path):
        for line in path.read_text().splitlines():
            if line.strip().startswith('code:'):
                return line.split(':', 1)[1].strip()
        msg = f'No code line in recovery file:\n{path.read_text()}'
        raise AssertionError(msg)

    @staticmethod
    def _redirect_recovery_file(monkeypatch, tmp_path):
        from services import admin_recovery

        path = tmp_path / 'admin-recovery.txt'
        monkeypatch.setattr(admin_recovery, 'RECOVERY_FILE_PATH', str(path))
        return path

    def test_full_recovery_flow(self, test_database, monkeypatch, tmp_path):
        from main import app

        path = self._redirect_recovery_file(monkeypatch, tmp_path)

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})

        anon = TestClient(app)
        assert (
            anon.post('/auth/admin-recovery/request', json={'username': 'admin'}).status_code == 200
        )
        assert path.exists()

        code = self._code_from_file(path)
        resp = anon.post(
            '/auth/admin-recovery/complete',
            json={'username': 'admin', 'code': code, 'new_password': 'recovered123'},
        )
        assert resp.status_code == 200
        # Signed straight in.
        assert anon.get('/auth/me').json()['username'] == 'admin'

        assert not path.exists()
        assert (
            TestClient(app)
            .post('/auth/login', json={'username': 'admin', 'password': 'recovered123'})
            .status_code
            == 200
        )

    def test_code_is_single_use(self, test_database, monkeypatch, tmp_path):
        from main import app

        path = self._redirect_recovery_file(monkeypatch, tmp_path)

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})

        anon = TestClient(app)
        anon.post('/auth/admin-recovery/request', json={'username': 'admin'})
        code = self._code_from_file(path)

        anon.post(
            '/auth/admin-recovery/complete',
            json={'username': 'admin', 'code': code, 'new_password': 'recovered123'},
        )
        replay = anon.post(
            '/auth/admin-recovery/complete',
            json={'username': 'admin', 'code': code, 'new_password': 'again12345'},
        )
        assert replay.status_code == 400

    def test_wrong_code_rejected(self, test_database, monkeypatch, tmp_path):
        from main import app

        self._redirect_recovery_file(monkeypatch, tmp_path)

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})

        anon = TestClient(app)
        anon.post('/auth/admin-recovery/request', json={'username': 'admin'})
        resp = anon.post(
            '/auth/admin-recovery/complete',
            json={'username': 'admin', 'code': 'WRNG-CODE-HERE', 'new_password': 'recovered123'},
        )
        assert resp.status_code == 400

    def test_expired_code_rejected(self, test_database, monkeypatch, tmp_path):
        from datetime import timedelta

        from sqlalchemy import update

        from database import db
        from main import app
        from models import User, utc_now

        path = self._redirect_recovery_file(monkeypatch, tmp_path)

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})

        anon = TestClient(app)
        anon.post('/auth/admin-recovery/request', json={'username': 'admin'})
        code = self._code_from_file(path)

        session = db.get_sync_session()
        try:
            session.execute(
                update(User)
                .where(User.username == 'admin')
                .values(recovery_code_expires_at=utc_now() - timedelta(minutes=1))
            )
            session.commit()
        finally:
            session.close()

        resp = anon.post(
            '/auth/admin-recovery/complete',
            json={'username': 'admin', 'code': code, 'new_password': 'recovered123'},
        )
        assert resp.status_code == 400

    def test_non_admin_gets_no_file(self, test_database, monkeypatch, tmp_path):
        """Requesting recovery for a non-admin looks identical but writes nothing."""
        from main import app

        path = self._redirect_recovery_file(monkeypatch, tmp_path)
        _register_admin_and_member(app)

        resp = TestClient(app).post('/auth/admin-recovery/request', json={'username': 'member'})
        assert resp.status_code == 200
        assert not path.exists()

    def test_unknown_username_gets_no_file(self, test_database, monkeypatch, tmp_path):
        from main import app

        path = self._redirect_recovery_file(monkeypatch, tmp_path)

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})

        resp = TestClient(app).post('/auth/admin-recovery/request', json={'username': 'ghost'})
        assert resp.status_code == 200
        assert not path.exists()

    def test_live_code_is_not_reissued(self, test_database, monkeypatch, tmp_path):
        """A second request must not invalidate the code the admin is already fetching."""
        from main import app

        path = self._redirect_recovery_file(monkeypatch, tmp_path)

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})

        anon = TestClient(app)
        anon.post('/auth/admin-recovery/request', json={'username': 'admin'})
        first_code = self._code_from_file(path)

        anon.post('/auth/admin-recovery/request', json={'username': 'admin'})
        assert self._code_from_file(path) == first_code

    def test_recovery_signs_out_existing_sessions(self, test_database, monkeypatch, tmp_path):
        from main import app

        path = self._redirect_recovery_file(monkeypatch, tmp_path)

        client = TestClient(app)
        client.post('/auth/register', json={'username': 'admin', 'password': 'admin123'})
        assert client.get('/auth/me').status_code == 200

        anon = TestClient(app)
        anon.post('/auth/admin-recovery/request', json={'username': 'admin'})
        anon.post(
            '/auth/admin-recovery/complete',
            json={
                'username': 'admin',
                'code': self._code_from_file(path),
                'new_password': 'recovered123',
            },
        )

        assert client.get('/auth/me').status_code == 401
