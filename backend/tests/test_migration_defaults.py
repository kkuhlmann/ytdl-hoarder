"""The `app_settings` row is INSERTed by the baseline migration, not by the SQLModel
field defaults, so `models.py`'s defaults are documentation until something checks them.
This is the check: the seeded row must equal APP_SETTINGS_DEFAULTS."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from models import APP_SETTINGS_DEFAULTS

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / 'alembic.ini'
APP_DIR = BACKEND_DIR / 'app'
SCRATCH_DB = 'migration_defaults_check'

# Every settings column, since the baseline seeds them all with literals. Derived from
# the constant rather than listed, so a new column is covered the moment it is added to
# APP_SETTINGS_DEFAULTS — the migration then has to seed it or this test fails.
SEEDED_COLUMNS = tuple(APP_SETTINGS_DEFAULTS)


@pytest.fixture(scope='module')
def migrated_settings_row(postgres_container, tmp_path_factory):
    admin_url = postgres_container.get_connection_url().replace(
        'postgresql+psycopg2://', 'postgresql+psycopg://'
    )
    admin_engine = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {SCRATCH_DB}'))
        conn.execute(text(f'CREATE DATABASE {SCRATCH_DB}'))
    admin_engine.dispose()

    scratch_url = admin_url.rsplit('/', 1)[0] + f'/{SCRATCH_DB}'

    # Run alembic out-of-process: migrations/env.py overwrites sqlalchemy.url from
    # `config.settings`, and config.py resolves config.yml relative to the CWD — so the
    # only reliable way to aim it at a scratch database is a CWD with no config.yml above
    # it, plus DATABASE__URL.
    env = {
        **os.environ,
        'DATABASE__URL': scratch_url.replace('postgresql+psycopg://', 'postgresql://'),
        'PYTHONPATH': str(APP_DIR),
    }
    result = subprocess.run(
        [sys.executable, '-m', 'alembic', '-c', str(ALEMBIC_INI), 'upgrade', 'head'],
        cwd=tmp_path_factory.mktemp('alembic-cwd'),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f'alembic upgrade head failed:\n{result.stderr}'

    engine = create_engine(scratch_url)
    with engine.connect() as conn:
        columns = ', '.join(SEEDED_COLUMNS)
        query = text(f'SELECT {columns} FROM app_settings WHERE id = 1')  # noqa: S608 — literals
        row = conn.execute(query).mappings().one()
    engine.dispose()
    return dict(row)


@pytest.mark.parametrize('column', SEEDED_COLUMNS)
def test_migrated_row_matches_the_model_default(migrated_settings_row, column):
    assert migrated_settings_row[column] == APP_SETTINGS_DEFAULTS[column]
