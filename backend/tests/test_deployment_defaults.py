"""Deployment-default hardening: the boot guard, the auth cookie, the CORS policy, API docs.

Each of these is what a stranger inherits by copying `config.sample.yml` verbatim, so
the defaults themselves are asserted rather than only the injected values.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import main
from config import DEFAULT_INSECURE_SECRET_KEY, AuthSettings, settings
from routers.auth import _set_auth_cookie

REAL_SECRET = 'f0e1d2c3b4a5968778695a4b3c2d1e0f' * 2


class StartupReachedError(Exception):
    """Sentinel proving control passed the secret-key guard."""


def cookie_attributes(response: Response) -> set[str]:
    return {part.strip().lower() for part in response.headers['set-cookie'].split(';')}


class TestSecretKeyBootGuard:
    async def test_refuses_to_boot_on_the_sample_secret(self, monkeypatch):
        monkeypatch.setattr(settings.auth, 'secret_key', DEFAULT_INSECURE_SECRET_KEY)
        stub_db = MagicMock()
        monkeypatch.setattr(main, 'db', stub_db)

        with pytest.raises(RuntimeError, match=r'auth\.secret_key'):
            async with main.lifespan(main.app):
                pass

        # The guard has to precede the ~90MB model download and orch.start(), or a
        # misconfigured deploy pays for a full boot and leaks a running orchestrator.
        stub_db.initialize_database.assert_not_called()

    async def test_a_real_secret_passes_the_guard(self, monkeypatch):
        monkeypatch.setattr(settings.auth, 'secret_key', REAL_SECRET)
        stub_db = MagicMock()
        stub_db.initialize_database.side_effect = StartupReachedError
        monkeypatch.setattr(main, 'db', stub_db)

        with pytest.raises(StartupReachedError):
            async with main.lifespan(main.app):
                pass

    def test_shipped_default_is_the_value_the_guard_rejects(self, monkeypatch):
        monkeypatch.delenv('AUTH__SECRET_KEY', raising=False)
        assert AuthSettings().secret_key == DEFAULT_INSECURE_SECRET_KEY


class TestAuthCookieSecureFlag:
    @pytest.mark.parametrize('cookie_secure', [True, False])
    def test_secure_flag_follows_config(self, monkeypatch, cookie_secure):
        monkeypatch.setattr(settings.auth, 'cookie_secure', cookie_secure)
        response = Response()

        _set_auth_cookie(response, 'a-token')

        assert ('secure' in cookie_attributes(response)) is cookie_secure

    def test_defaults_to_off_so_plain_http_self_hosts_keep_working(self, monkeypatch):
        monkeypatch.delenv('AUTH__COOKIE_SECURE', raising=False)
        assert AuthSettings().cookie_secure is False

    def test_existing_cookie_flags_survive(self, monkeypatch):
        monkeypatch.setattr(settings.auth, 'cookie_secure', True)
        response = Response()

        _set_auth_cookie(response, 'a-token')

        assert {'httponly', 'samesite=lax', 'path=/'} <= cookie_attributes(response)


def cors_client(origins: list[str]) -> TestClient:
    """A throwaway app wired exactly as `main` wires the real one, for the given origins."""
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **main.cors_kwargs(origins))

    @app.get('/probe')
    def probe():
        return {'ok': True}

    return TestClient(app)


class TestCorsKwargs:
    def test_no_origins_falls_through_to_the_any_origin_regex(self):
        kwargs = main.cors_kwargs([])

        assert kwargs['allow_origin_regex'] == '.*'
        assert kwargs['allow_origins'] == []

    def test_listed_origins_drop_the_regex(self):
        kwargs = main.cors_kwargs(['http://localhost:3000'])

        assert kwargs['allow_origins'] == ['http://localhost:3000']
        assert kwargs['allow_origin_regex'] is None

    def test_credentials_are_allowed_either_way(self):
        assert main.cors_kwargs([])['allow_credentials'] is True
        assert main.cors_kwargs(['http://localhost:3000'])['allow_credentials'] is True


class TestCorsDefaultAllowsAnyOrigin:
    """Empty is the shipped default: dev cannot know the address the browser will use."""

    def test_the_default_is_empty(self, monkeypatch):
        monkeypatch.delenv('AUTH__ALLOWED_ORIGINS', raising=False)
        assert AuthSettings().allowed_origins == []

    def test_any_origin_is_echoed_with_credentials(self):
        resp = cors_client([]).get('/probe', headers={'Origin': 'https://evil.example'})

        assert resp.headers['access-control-allow-origin'] == 'https://evil.example'
        assert resp.headers['access-control-allow-credentials'] == 'true'

    def test_the_echo_varies_on_origin(self):
        """Without this a shared cache could serve one origin's response to another."""
        resp = cors_client([]).get('/probe', headers={'Origin': 'https://evil.example'})

        assert 'origin' in resp.headers['vary'].lower()

    def test_a_preflight_from_any_origin_is_answered(self):
        resp = cors_client([]).options(
            '/probe',
            headers={'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'GET'},
        )

        assert resp.headers['access-control-allow-origin'] == 'https://evil.example'


class TestCorsAllowlistIsOptIn:
    """Listing origins restores the strict allowlist, which is the whole point of keeping
    the setting rather than hardcoding the open default."""

    def test_allowlist_denies_a_foreign_origin(self):
        resp = cors_client(['http://localhost:3000']).get(
            '/probe', headers={'Origin': 'https://evil.example'}
        )

        assert 'access-control-allow-origin' not in resp.headers

    def test_allowlist_still_permits_the_dev_frontend(self):
        resp = cors_client(['http://localhost:3000']).get(
            '/probe', headers={'Origin': 'http://localhost:3000'}
        )

        assert resp.headers['access-control-allow-origin'] == 'http://localhost:3000'
        assert resp.headers['access-control-allow-credentials'] == 'true'

    def test_preflight_from_a_foreign_origin_is_denied(self):
        resp = cors_client(['http://localhost:3000']).options(
            '/probe',
            headers={'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'GET'},
        )

        assert 'access-control-allow-origin' not in resp.headers


class TestApiDocsAreDevOnly:
    def test_production_unregisters_all_three(self):
        assert main.docs_kwargs(True) == {
            'openapi_url': None,
            'docs_url': None,
            'redoc_url': None,
        }

    def test_dev_keeps_fastapis_own_defaults(self):
        assert main.docs_kwargs(False) == {}

    def test_the_kwargs_actually_drop_the_routes(self):
        """None unregisters rather than relocating — asserted on a throwaway app, since
        `main.app` is built at import time and reloading it would poison the session."""
        app = FastAPI(**main.docs_kwargs(True))

        @app.get('/probe')
        def probe():
            return {'ok': True}

        client = TestClient(app)

        assert client.get('/probe').status_code == 200
        for path in ('/openapi.json', '/docs', '/redoc'):
            assert client.get(path).status_code == 404


@pytest.mark.skipif(main.SERVE_FRONTEND, reason='API docs are only served in API-only dev mode')
class TestApiDocsAreWiredIntoTheApp:
    def test_schema_is_served_in_dev(self):
        resp = TestClient(main.app).get('/openapi.json')

        assert resp.status_code == 200
        assert resp.json()['openapi']

    def test_swagger_ui_is_served_in_dev(self):
        assert TestClient(main.app).get('/docs').status_code == 200


@pytest.mark.skipif(main.SERVE_FRONTEND, reason='CORS is only mounted in API-only dev mode')
class TestCorsIsWiredIntoTheApp:
    def test_the_loaded_settings_reach_the_middleware(self):
        """Passes under either policy, so a config.yml that opts into an allowlist
        doesn't turn this into a failure on the developer's own machine."""
        configured = settings.auth.allowed_origins
        origin = configured[0] if configured else 'https://any.example'

        resp = TestClient(main.app).get('/health', headers={'Origin': origin})

        assert resp.headers['access-control-allow-origin'] == origin
