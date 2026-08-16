"""Path-containment tests for the SPA catch-all route.

The catch-all is only mounted in the production image, which is the artifact users
are told to deploy, and it is unauthenticated. uvicorn percent-decodes the request
path before routing and Starlette's `:path` convertor matches `..`, so anything the
handler joins onto STATIC_DIR must be re-checked after resolution.
"""

from urllib.parse import unquote

import pytest

import main


@pytest.fixture
def static_root(tmp_path, monkeypatch):
    """Build a static tree plus a secret sibling that must never be served."""
    root = tmp_path / 'static'
    (root / 'nested').mkdir(parents=True)
    (root / 'index.html').write_text('<!doctype html>SPA')
    (root / 'favicon.ico').write_text('icon')
    (root / 'nested' / 'index.html').write_text('nested page')

    (tmp_path / 'secret.yml').write_text('auth:\n  secret_key: hunter2\n')

    monkeypatch.setattr(main, 'STATIC_DIR', root)
    return root


@pytest.mark.parametrize(
    'path',
    [
        '../secret.yml',
        '../../etc/passwd',
        unquote('%2e%2e/%2e%2e/etc/app/config.yml'),
        unquote('%2e%2e%2f%2e%2e%2fdata/cookies.txt'),
        'nested/../../secret.yml',
        './../secret.yml',
        # A leading slash makes the right operand absolute, and `/` discards the
        # left operand entirely rather than joining.
        '/etc/passwd',
        '/data/admin-recovery.txt',
    ],
)
def test_traversal_falls_back_to_index(static_root, path):
    assert main.resolve_spa_file(path) == static_root / 'index.html'


def test_symlink_out_of_root_is_rejected(static_root, tmp_path):
    (static_root / 'escape.yml').symlink_to(tmp_path / 'secret.yml')

    assert main.resolve_spa_file('escape.yml') == static_root / 'index.html'


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        ('favicon.ico', 'favicon.ico'),
        ('index.html', 'index.html'),
        ('nested/index.html', 'nested/index.html'),
        # trailingSlash: true — a directory resolves to its index.html
        ('nested', 'nested/index.html'),
        ('nested/', 'nested/index.html'),
    ],
)
def test_real_files_are_served(static_root, path, expected):
    assert main.resolve_spa_file(path) == static_root / expected


@pytest.mark.parametrize('path', ['', 'downloads', 'settings/users', 'does-not-exist.js'])
def test_unknown_paths_fall_back_to_index(static_root, path):
    """Client-side routes have no file on disk and must still boot the SPA."""
    assert main.resolve_spa_file(path) == static_root / 'index.html'


def test_null_byte_does_not_raise(static_root):
    """A NUL in the path makes stat() raise ValueError/OSError instead of returning."""
    assert main.resolve_spa_file('index.html\x00.png') == static_root / 'index.html'
