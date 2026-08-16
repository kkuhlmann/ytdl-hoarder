"""Repository for MediaAccess CRUD operations.

Tracks which users have access to which media items.

Each MediaAccess row tracks the *source* of access:
- source_type=SourceType.DIRECT, source_id=0: Owner access or explicit share
- source_type=SourceType.PLAYLIST, source_id=<playlist_id>: Access via shared playlist
- source_type=SourceType.SUBSCRIPTION, source_id=<subscription_id>: Access via shared subscription

A user can have multiple rows for the same media if access comes from different sources.
Revoking one source doesn't affect others.
"""

from fastapi import HTTPException, status
from sqlalchemy import case, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlmodel import select

from database import db
from logger import logger
from models import MediaAccess, MediaDetails, SourceType, utc_now

# --- Async functions for FastAPI ---


async def add_access(
    user_id: int,
    media_details_id: int,
    source_type: str = SourceType.DIRECT,
    source_id: int = 0,
) -> MediaAccess:
    """Grant a user access to a media item. Idempotent (no-op if already exists for same source)."""
    async with db.get_async_session() as session:
        stmt = select(MediaAccess).where(
            MediaAccess.user_id == user_id,
            MediaAccess.media_details_id == media_details_id,
            MediaAccess.source_type == source_type,
            MediaAccess.source_id == source_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            return existing

        access = MediaAccess(
            user_id=user_id,
            media_details_id=media_details_id,
            source_type=source_type,
            source_id=source_id,
        )
        session.add(access)
        await session.commit()
        await session.refresh(access)
        return access


def _build_access_rows(
    user_ids: list[int], media_ids: list[int], source_type: str, source_id: int
) -> list[dict]:
    """Build deduplicated (user × media) row dicts for a bulk MediaAccess insert."""
    source_value = getattr(source_type, 'value', source_type)
    pairs = dict.fromkeys((uid, mid) for uid in user_ids for mid in media_ids)
    return [
        {
            'user_id': uid,
            'media_details_id': mid,
            'source_type': source_value,
            'source_id': source_id,
            'created_at': utc_now(),
        }
        for uid, mid in pairs
    ]


async def add_access_bulk(
    user_ids: list[int],
    media_ids: list[int],
    source_type: str = SourceType.DIRECT,
    source_id: int = 0,
    session: AsyncSession | None = None,
) -> int:
    """Grant many users access to many media items in a single INSERT.

    Inserts the (user × media) cross product, skipping rows that already exist
    for the same source (ON CONFLICT DO NOTHING on uq_media_access_user_media_source).
    Returns the number of rows actually inserted. When `session` is provided,
    the statement joins the caller's transaction (caller commits).
    """
    rows = _build_access_rows(user_ids, media_ids, source_type, source_id)
    if not rows:
        return 0
    # RETURNING gives a reliable inserted-row count across drivers
    # (psycopg reports rowcount=-1 for multi-values INSERT .. ON CONFLICT).
    stmt = (
        pg_insert(MediaAccess)
        .values(rows)
        .on_conflict_do_nothing(constraint='uq_media_access_user_media_source')
        .returning(MediaAccess.id)
    )
    async with db.use_async_session(session) as s:
        result = await s.execute(stmt)
        return len(result.scalars().all())


async def remove_access(
    user_id: int,
    media_details_id: int,
    source_type: str = SourceType.DIRECT,
    source_id: int = 0,
) -> bool:
    """Remove a user's access to a media item for a specific source. Returns True if removed."""
    async with db.get_async_session() as session:
        stmt = select(MediaAccess).where(
            MediaAccess.user_id == user_id,
            MediaAccess.media_details_id == media_details_id,
            MediaAccess.source_type == source_type,
            MediaAccess.source_id == source_id,
        )
        result = await session.execute(stmt)
        access = result.scalar_one_or_none()

        if not access:
            return False

        await session.delete(access)
        await session.commit()
        return True


async def remove_access_by_source(
    user_id: int, source_type: str, source_id: int, session: AsyncSession | None = None
) -> int:
    """Remove all MediaAccess rows for a user from a specific source.

    Used when:
    - Shared user removes a playlist → remove_access_by_source(uid, SourceType.PLAYLIST, playlist_id)
    - Shared user removes a subscription → remove_access_by_source(uid, SourceType.SUBSCRIPTION, sub_id)
    - Owner unshares a playlist/subscription from a user → same call

    When `session` is provided, the DELETE joins the caller's transaction.
    Returns the number of rows deleted.
    """
    stmt = delete(MediaAccess).where(
        MediaAccess.user_id == user_id,
        MediaAccess.source_type == source_type,
        MediaAccess.source_id == source_id,
    )
    async with db.use_async_session(session) as s:
        result = await s.execute(stmt)
        return result.rowcount


async def remove_media_access_by_source(
    media_details_id: int, source_type: str, source_id: int
) -> int:
    """Remove all MediaAccess rows for a specific media from a specific source.

    Used when owner removes a media item from a shared playlist.

    Returns the number of rows deleted.
    """
    async with db.get_async_session() as session:
        stmt = delete(MediaAccess).where(
            MediaAccess.media_details_id == media_details_id,
            MediaAccess.source_type == source_type,
            MediaAccess.source_id == source_id,
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount


async def has_access(user_id: int, media_details_id: int) -> bool:
    """Check if a user has access to a media item (any source)."""
    async with db.get_async_session() as session:
        stmt = select(MediaAccess).where(
            MediaAccess.user_id == user_id,
            MediaAccess.media_details_id == media_details_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def has_direct_access(user_id: int, media_details_id: int) -> bool:
    """Check if a user has direct (non-inherited) access to a media item."""
    async with db.get_async_session() as session:
        stmt = select(MediaAccess).where(
            MediaAccess.user_id == user_id,
            MediaAccess.media_details_id == media_details_id,
            MediaAccess.source_type == SourceType.DIRECT,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def get_users_with_access(media_details_id: int) -> list[int]:
    async with db.get_async_session() as session:
        stmt = select(func.distinct(MediaAccess.user_id)).where(
            MediaAccess.media_details_id == media_details_id
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]


async def get_transfer_candidate_user_ids(media_details_id: int, exclude_user_id: int) -> list[int]:
    """Get user IDs with any access to the media, excluding a specific user.

    Ordered by source preference (DIRECT, then SUBSCRIPTION, then PLAYLIST), earliest
    created_at first within each, deduplicated. Used to find ownership transfer
    candidates when the owner deletes media — any access holder qualifies, so an
    owner's delete never destroys a file another user can still reach.
    """
    source_preference = case(
        (MediaAccess.source_type == SourceType.DIRECT, 0),
        (MediaAccess.source_type == SourceType.SUBSCRIPTION, 1),
        else_=2,
    )
    async with db.get_async_session() as session:
        stmt = (
            select(MediaAccess.user_id)
            .where(
                MediaAccess.media_details_id == media_details_id,
                MediaAccess.user_id != exclude_user_id,
            )
            .order_by(source_preference, MediaAccess.created_at.asc())
        )
        result = await session.execute(stmt)
        user_ids: list[int] = []
        for (user_id,) in result.all():
            if user_id not in user_ids:
                user_ids.append(user_id)
        return user_ids


async def remove_all_access_for_media(media_details_id: int) -> int:
    """Remove ALL MediaAccess rows for a given media (all users, all sources).

    Used on true soft delete to prevent orphaned access rows.
    Returns the number of rows deleted.
    """
    async with db.get_async_session() as session:
        stmt = delete(MediaAccess).where(
            MediaAccess.media_details_id == media_details_id,
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount


async def remove_user_access_for_media(user_id: int, media_details_id: int) -> int:
    """Remove ALL MediaAccess rows for a specific user+media (all source types).

    Used to strip the departing owner of all access to transferred media.
    Returns the number of rows deleted.
    """
    async with db.get_async_session() as session:
        stmt = delete(MediaAccess).where(
            MediaAccess.user_id == user_id,
            MediaAccess.media_details_id == media_details_id,
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount


async def user_can_access_media(user_id: int, media: MediaDetails, is_admin: bool = False) -> bool:
    """Three-tier media access check: owner → shared (MediaAccess row) → admin.

    The owner tier is checked via owner_id so the owner keeps access even if
    their DIRECT MediaAccess row was removed (e.g. by an unshare targeting them).
    """
    if is_admin:
        return True
    if media.owner_id == user_id:
        return True
    return await has_access(user_id, media.id)


async def check_access_or_raise(user_id: int, media: MediaDetails, is_admin: bool = False):
    """Check owner/shared/admin access to a media item and raise HTTP 404 if denied."""
    if not await user_can_access_media(user_id, media, is_admin=is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'MediaDetails with id: {media.id} not found',
        )


async def check_media_owner_or_raise(user_id: int, media: MediaDetails, is_admin: bool = False):
    """Check if a user owns a media item and raise HTTP 404 if not.

    Only owners and admins can share/unshare media.
    """
    if is_admin:
        return
    if media.owner_id == user_id:
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f'MediaDetails with id: {media.id} not found',
    )


# --- Sync functions (job bodies run in lane threads / the ML child) ---


def sync_add_access(
    user_id: int,
    media_details_id: int,
    source_type: str = SourceType.DIRECT,
    source_id: int = 0,
) -> int:
    """Sync version: Grant a user access to a media item. Returns rows inserted (0 or 1).

    Idempotent under concurrency (ON CONFLICT DO NOTHING) and tolerant of the
    media row being hard-deleted by a concurrent chain: an FK violation is logged
    and swallowed instead of killing the calling task — the grant is meaningless
    once the row is gone, and the next subscription tick re-grants against the
    replacement row.
    """
    rows = _build_access_rows([user_id], [media_details_id], source_type, source_id)
    stmt = (
        pg_insert(MediaAccess)
        .values(rows)
        .on_conflict_do_nothing(constraint='uq_media_access_user_media_source')
        .returning(MediaAccess.id)
    )
    try:
        with db.sync_session() as session:
            result = session.execute(stmt)
            return len(result.scalars().all())
    except IntegrityError:
        logger.warning(
            f'Skipping media_access grant for user {user_id} → media {media_details_id}: '
            f'media row no longer exists (superseded by a concurrent chain)'
        )
        return 0


def sync_add_access_bulk(
    user_ids: list[int],
    media_ids: list[int],
    source_type: str = SourceType.DIRECT,
    source_id: int = 0,
    session: Session | None = None,
) -> int:
    """Sync version of add_access_bulk for job bodies."""
    rows = _build_access_rows(user_ids, media_ids, source_type, source_id)
    if not rows:
        return 0
    stmt = (
        pg_insert(MediaAccess)
        .values(rows)
        .on_conflict_do_nothing(constraint='uq_media_access_user_media_source')
        .returning(MediaAccess.id)
    )
    with db.use_sync_session(session) as s:
        result = s.execute(stmt)
        return len(result.scalars().all())
