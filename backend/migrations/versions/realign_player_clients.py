"""Realign YouTube player clients for yt-dlp 2026.08.19

The stored `app_settings` lists are the ones actually used at runtime — `models.py`'s
defaults only seed a fresh row — so a default change alone would leave every existing
install on `android_vr`, whose formats YouTube has 403'd since 2026-08-17 (yt-dlp PR
#17461 dropped it from yt-dlp's own defaults for that reason). This rewrites the stored
lists so existing installs pick up the fix without a Settings-UI visit.

Revision ID: realign_player_clients
Revises: baseline_schema
Create Date: 2026-08-30

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'realign_player_clients'
down_revision: str | None = 'baseline_schema'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PLAYER_CLIENTS = '["visionos", "tv_simply", "web_safari", "web", "web_embedded"]'
NEW_COOKIES_PLAYER_CLIENTS = '["web_embedded", "tv_downgraded", "web", "web_safari", "mweb"]'

OLD_PLAYER_CLIENTS = '["android_vr", "tv", "tv_simply", "web", "web_safari"]'
OLD_COOKIES_PLAYER_CLIENTS = '["tv_downgraded", "web", "web_safari", "mweb", "web_embedded"]'


def _rewrite(player_client: str, cookies_player_client: str) -> None:
    op.execute(f"""
        UPDATE app_settings
        SET player_client = '{player_client}'::json,
            cookies_player_client = '{cookies_player_client}'::json,
            updated_at = NOW()
    """)


def upgrade() -> None:
    _rewrite(NEW_PLAYER_CLIENTS, NEW_COOKIES_PLAYER_CLIENTS)


def downgrade() -> None:
    _rewrite(OLD_PLAYER_CLIENTS, OLD_COOKIES_PLAYER_CLIENTS)
