"""
Settings API router for managing app-wide configuration.
"""

import os
import tempfile
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from dependencies import get_admin_user_id
from logger import logger
from models import APP_SETTINGS_DEFAULTS, COOKIE_FILE_PATH, VALID_PLAYER_CLIENTS, CookiesMode
from orchestrator import orch
from orchestrator.scheduler import subscription_schedule
from repositories import settings as settings_repo

router = APIRouter()


class SettingsUpdate(BaseModel):
    """Request model for partial settings update."""

    download_sleep_seconds: int | None = None
    download_rate_limit_kbps: int | None = None
    request_sleep_seconds: int | None = None
    cleanup_age_hours: int | None = None
    player_client: list[str] | None = None
    cookies_mode: str | None = None
    cookies_player_client: list[str] | None = None
    transcript_chunk_duration: int | None = None
    transcript_block_duration: int | None = None
    force_whisper_transcription: bool | None = None
    subscription_table_page_size: int | None = None
    download_table_page_size: int | None = None
    subscription_check_minutes: int | None = None
    default_lane_concurrency: int | None = None
    downloads_lane_concurrency: int | None = None
    subscriptions_lane_concurrency: int | None = None
    ml_lane_concurrency: int | None = None


MIN_LANE_CONCURRENCY = 1
MAX_LANE_CONCURRENCY = 8
MIN_SUBSCRIPTION_CHECK_MINUTES = 1
MAX_SUBSCRIPTION_CHECK_MINUTES = 24 * 60
# A per-request sleep is paid once per HTTP request during extraction, so a large value
# multiplies across a channel enumeration into a pipeline stall.
MAX_REQUEST_SLEEP_SECONDS = 60


def _apply_lane_concurrency(settings) -> None:
    """Push lane widths to the running orchestrator. Idempotent, so every write
    path can call it unconditionally rather than detecting which keys changed."""
    orch.set_lane_concurrency(settings_repo.lane_concurrency(settings))


def _apply_subscription_interval(settings) -> None:
    """Retarget the running cron scheduler. Idempotent, like _apply_lane_concurrency."""
    subscription_schedule.set_minutes(settings.subscription_check_minutes)


def _settings_to_dict(settings) -> dict[str, Any]:
    return {
        'download_sleep_seconds': settings.download_sleep_seconds,
        'download_rate_limit_kbps': settings.download_rate_limit_kbps,
        'request_sleep_seconds': settings.request_sleep_seconds,
        'cleanup_age_hours': settings.cleanup_age_hours,
        'player_client': settings.player_client,
        'cookies_mode': settings.cookies_mode,
        'cookies_player_client': settings.cookies_player_client,
        'transcript_chunk_duration': settings.transcript_chunk_duration,
        'transcript_block_duration': settings.transcript_block_duration,
        'force_whisper_transcription': settings.force_whisper_transcription,
        'subscription_table_page_size': settings.subscription_table_page_size,
        'download_table_page_size': settings.download_table_page_size,
        'subscription_check_minutes': settings.subscription_check_minutes,
        'default_lane_concurrency': settings.default_lane_concurrency,
        'downloads_lane_concurrency': settings.downloads_lane_concurrency,
        'subscriptions_lane_concurrency': settings.subscriptions_lane_concurrency,
        'ml_lane_concurrency': settings.ml_lane_concurrency,
        'updated_at': settings.updated_at.isoformat() if settings.updated_at else None,
    }


@router.get(
    '',
    status_code=status.HTTP_200_OK,
    response_description='Current application settings',
)
async def get_settings(_user_id: int = Depends(get_admin_user_id)) -> dict[str, Any]:
    """Get current application settings."""
    settings = await settings_repo.get_settings()
    return _settings_to_dict(settings)


@router.put(
    '',
    status_code=status.HTTP_200_OK,
    response_description='Updated application settings',
)
async def update_settings(  # noqa: C901 — one branch per independently-updatable setting
    updates: SettingsUpdate, _user_id: int = Depends(get_admin_user_id)
) -> dict[str, Any]:
    """
    Update application settings.

    Only provided fields will be updated (partial update).
    Settings take effect on next task execution.
    """
    update_dict = {k: v for k, v in updates.model_dump().items() if v is not None}

    if not update_dict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='No settings to update',
        )

    if 'download_sleep_seconds' in update_dict and update_dict['download_sleep_seconds'] < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='download_sleep_seconds must be non-negative',
        )

    if 'download_rate_limit_kbps' in update_dict and update_dict['download_rate_limit_kbps'] < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='download_rate_limit_kbps must be non-negative',
        )

    if 'request_sleep_seconds' in update_dict and not (
        0 <= update_dict['request_sleep_seconds'] <= MAX_REQUEST_SLEEP_SECONDS
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'request_sleep_seconds must be between 0 and {MAX_REQUEST_SLEEP_SECONDS}',
        )

    if 'cleanup_age_hours' in update_dict and update_dict['cleanup_age_hours'] < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='cleanup_age_hours must be at least 1',
        )

    if 'transcript_chunk_duration' in update_dict and update_dict['transcript_chunk_duration'] < 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='transcript_chunk_duration must be at least 60 seconds',
        )

    if 'transcript_block_duration' in update_dict and update_dict['transcript_block_duration'] < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='transcript_block_duration must be at least 5 seconds',
        )

    page_size_fields = ['subscription_table_page_size', 'download_table_page_size']
    for field in page_size_fields:
        if field in update_dict and (update_dict[field] < 5 or update_dict[field] > 100):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'{field} must be between 5 and 100',
            )

    if 'subscription_check_minutes' in update_dict and not (
        MIN_SUBSCRIPTION_CHECK_MINUTES
        <= update_dict['subscription_check_minutes']
        <= MAX_SUBSCRIPTION_CHECK_MINUTES
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f'subscription_check_minutes must be between {MIN_SUBSCRIPTION_CHECK_MINUTES} '
                f'and {MAX_SUBSCRIPTION_CHECK_MINUTES}'
            ),
        )

    for field in settings_repo.LANE_CONCURRENCY_COLUMNS.values():
        if field in update_dict and not (
            MIN_LANE_CONCURRENCY <= update_dict[field] <= MAX_LANE_CONCURRENCY
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f'{field} must be between {MIN_LANE_CONCURRENCY} and {MAX_LANE_CONCURRENCY}'
                ),
            )

    for field in ['player_client', 'cookies_player_client']:
        if field in update_dict:
            for client in update_dict[field]:
                if client not in VALID_PLAYER_CLIENTS:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid {field} '{client}'. Valid options: {VALID_PLAYER_CLIENTS}",
                    )

    valid_cookies_modes = [m.value for m in CookiesMode]
    if 'cookies_mode' in update_dict and update_dict['cookies_mode'] not in valid_cookies_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cookies_mode '{update_dict['cookies_mode']}'. Valid options: {valid_cookies_modes}",
        )

    logger.info(f'Updating settings: {update_dict}')
    settings = await settings_repo.update_settings(update_dict)
    _apply_lane_concurrency(settings)
    _apply_subscription_interval(settings)

    return _settings_to_dict(settings)


@router.put(
    '/reset/{key}',
    status_code=status.HTTP_200_OK,
    response_description='Reset single setting to default',
)
async def reset_setting(key: str, _user_id: int = Depends(get_admin_user_id)) -> dict[str, Any]:
    """
    Reset a single setting to its default value.

    Args:
        key: The setting name to reset (e.g., 'download_sleep_seconds').
    """
    if key not in APP_SETTINGS_DEFAULTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown setting: '{key}'. Valid settings: {list(APP_SETTINGS_DEFAULTS.keys())}",
        )

    logger.info(f'Resetting setting {key} to default: {APP_SETTINGS_DEFAULTS[key]}')
    settings = await settings_repo.reset_setting(key)
    _apply_lane_concurrency(settings)
    _apply_subscription_interval(settings)

    result = _settings_to_dict(settings)
    result['reset_key'] = key
    result['reset_value'] = APP_SETTINGS_DEFAULTS[key]
    return result


@router.put(
    '/reset',
    status_code=status.HTTP_200_OK,
    response_description='Reset all settings to defaults',
)
async def reset_all_settings(_user_id: int = Depends(get_admin_user_id)) -> dict[str, Any]:
    """Reset all settings to their default values."""
    logger.info('Resetting all settings to defaults')
    settings = await settings_repo.reset_all_settings()
    _apply_lane_concurrency(settings)
    _apply_subscription_interval(settings)

    result = _settings_to_dict(settings)
    result['message'] = 'All settings reset to defaults'
    return result


MAX_COOKIE_FILE_SIZE = 1 * 1024 * 1024  # 1 MB


@router.get(
    '/cookies',
    status_code=status.HTTP_200_OK,
    response_description='Cookie file status',
)
async def get_cookie_status(_user_id: int = Depends(get_admin_user_id)) -> dict[str, Any]:
    """Get the current status of the cookie file."""
    settings = await settings_repo.get_settings()
    file_exists = os.path.isfile(COOKIE_FILE_PATH)
    file_size_bytes = os.path.getsize(COOKIE_FILE_PATH) if file_exists else 0

    return {
        'cookies_mode': settings.cookies_mode,
        'file_exists': file_exists,
        'file_size_bytes': file_size_bytes,
        'uploaded_at': settings.cookies_uploaded_at.isoformat()
        if settings.cookies_uploaded_at
        else None,
    }


@router.post(
    '/cookies',
    status_code=status.HTTP_200_OK,
    response_description='Cookie file uploaded',
)
async def upload_cookies(
    file: UploadFile = File(...), _user_id: int = Depends(get_admin_user_id)
) -> dict[str, Any]:
    """Upload a Netscape-format cookies.txt file for yt-dlp."""
    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cookie file is empty',
        )

    if len(content) > MAX_COOKIE_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Cookie file too large (max {MAX_COOKIE_FILE_SIZE // 1024}KB)',
        )

    # Write to temp file in the same directory, then atomic rename to final location
    cookie_dir = os.path.dirname(COOKIE_FILE_PATH)
    os.makedirs(cookie_dir, exist_ok=True)
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=cookie_dir)
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
        os.replace(tmp_path, COOKIE_FILE_PATH)
    except PermissionError as e:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f'Permission denied writing to {cookie_dir}. '
                'On Linux, run: sudo chown 1000:1000 data/'
            ),
        ) from e
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    uploaded_at = datetime.now(UTC).replace(tzinfo=None)
    settings = await settings_repo.get_settings()
    update_fields: dict[str, Any] = {'cookies_uploaded_at': uploaded_at}
    # If cookies are currently disabled, default to RETRIES_ONLY on upload
    if settings.cookies_mode == CookiesMode.NEVER.value:
        update_fields['cookies_mode'] = CookiesMode.RETRIES_ONLY.value
    await settings_repo.update_settings(update_fields)
    logger.info(f'Cookie file uploaded ({len(content)} bytes)')

    current_settings = await settings_repo.get_settings()
    return {
        'status': 'uploaded',
        'cookies_mode': current_settings.cookies_mode,
        'file_size_bytes': len(content),
        'uploaded_at': uploaded_at.isoformat(),
    }


@router.delete(
    '/cookies',
    status_code=status.HTTP_200_OK,
    response_description='Cookie file deleted',
)
async def delete_cookies(_user_id: int = Depends(get_admin_user_id)) -> dict[str, Any]:
    """Delete the cookie file and disable cookie authentication."""
    if os.path.isfile(COOKIE_FILE_PATH):
        os.unlink(COOKIE_FILE_PATH)

    await settings_repo.update_settings(
        {
            'cookies_mode': CookiesMode.NEVER.value,
            'cookies_uploaded_at': None,
        }
    )
    logger.info('Cookie file deleted')

    return {
        'status': 'deleted',
        'cookies_mode': CookiesMode.NEVER.value,
    }
