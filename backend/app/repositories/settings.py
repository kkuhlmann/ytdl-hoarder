"""
Settings repository for app-wide configuration.

Provides both async (for FastAPI) and sync (for job bodies) access.
Sync version includes a 60-second TTL cache to reduce DB hits in workers.
"""

import time
from typing import Any

from sqlmodel import select

from database import db
from logger import logger
from models import APP_SETTINGS_DEFAULTS, AppSettings, utc_now

# orchestrator.jobs, not the package: it is a leaf module, so importing it here
# cannot loop back through orchestrator.core's own repository imports.
from orchestrator.jobs import DEFAULT_LANE, DOWNLOADS_LANE, ML_LANE, SUBSCRIPTIONS_LANE

# Lane name → the app_settings column holding its width. The one place the two
# naming schemes meet, so both callers (the lifespan seed and the settings router's
# live apply) agree on it.
LANE_CONCURRENCY_COLUMNS = {
    DEFAULT_LANE: 'default_lane_concurrency',
    DOWNLOADS_LANE: 'downloads_lane_concurrency',
    SUBSCRIPTIONS_LANE: 'subscriptions_lane_concurrency',
    ML_LANE: 'ml_lane_concurrency',
}

# --- Cache for sync access from job bodies ---

_settings_cache: AppSettings | None = None
_settings_cache_time: float = 0
SETTINGS_CACHE_TTL_SECONDS = 60


def _is_cache_valid() -> bool:
    return (
        _settings_cache is not None
        and (time.time() - _settings_cache_time) < SETTINGS_CACHE_TTL_SECONDS
    )


def invalidate_cache() -> None:
    """Invalidate the settings cache. Call this after any update."""
    global _settings_cache, _settings_cache_time
    _settings_cache = None
    _settings_cache_time = 0


def lane_concurrency(settings: AppSettings) -> dict[str, int]:
    """Lane widths from a settings row, shaped for Orchestrator.set_lane_concurrency."""
    return {lane: getattr(settings, column) for lane, column in LANE_CONCURRENCY_COLUMNS.items()}


# --- Async functions for FastAPI ---


async def get_settings() -> AppSettings:
    """Get current settings. Creates default row if none exists."""
    async with db.get_async_session() as session:
        stmt = select(AppSettings).where(AppSettings.id == 1)
        result = await session.execute(stmt)
        settings = result.scalar_one_or_none()

        if settings is None:
            settings = AppSettings(id=1)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
            logger.info('Created default app_settings row')

        return settings


async def update_settings(updates: dict[str, Any]) -> AppSettings:
    """Partial update of settings."""
    async with db.get_async_session() as session:
        stmt = select(AppSettings).where(AppSettings.id == 1)
        result = await session.execute(stmt)
        settings = result.scalar_one_or_none()

        if settings is None:
            settings = AppSettings(id=1, **updates)
            session.add(settings)
        else:
            for key, value in updates.items():
                if hasattr(settings, key) and key not in ('id', 'updated_at'):
                    setattr(settings, key, value)
            settings.updated_at = utc_now()

        await session.commit()
        await session.refresh(settings)

        invalidate_cache()
        logger.info(f'Updated settings: {list(updates.keys())}')

        return settings


async def reset_setting(key: str) -> AppSettings:
    """Reset a single setting to its default value.

    Raises:
        ValueError: If key is not a valid setting name.
    """
    if key not in APP_SETTINGS_DEFAULTS:
        msg = f'Unknown setting: {key}'
        raise ValueError(msg)

    default_value = APP_SETTINGS_DEFAULTS[key]
    return await update_settings({key: default_value})


async def reset_all_settings() -> AppSettings:
    return await update_settings(APP_SETTINGS_DEFAULTS.copy())


# --- Sync functions (job bodies run in lane threads / the ML child) ---


def sync_get_settings() -> AppSettings:
    """Get current settings (sync version with 60s TTL cache).

    Uses an in-memory cache to reduce database hits. Cache is invalidated
    after updates or after 60 seconds.
    """
    global _settings_cache, _settings_cache_time

    if _is_cache_valid():
        return _settings_cache

    with db.sync_session() as session:
        stmt = select(AppSettings).where(AppSettings.id == 1)
        result = session.execute(stmt)
        settings = result.scalar_one_or_none()

        if settings is None:
            settings = AppSettings(id=1)
            session.add(settings)
            session.flush()
            session.refresh(settings)
            logger.info('Created default app_settings row (sync)')

        _settings_cache = settings
        _settings_cache_time = time.time()

        return settings
