"""Atomic share/unshare cascades spanning entity-access and media-access tables.

Each function runs its full cascade in a single transaction: the entity access
row(s) and the sourced MediaAccess rows commit or roll back together.
"""

from database import db
from models import SourceType
from repositories import media_access as ma_repo
from repositories import playlist_access as pa_repo
from repositories import subscription_access as sa_repo


async def _share_with_users(
    access_repo, source_type: SourceType, user_ids: list[int], entity_id: int, media_ids: list[int]
) -> int:
    async with db.get_async_session() as session:
        await access_repo.add_access_bulk(user_ids, entity_id, session=session)
        return await ma_repo.add_access_bulk(
            user_ids,
            media_ids,
            source_type=source_type,
            source_id=entity_id,
            session=session,
        )


async def _unshare_for_user(
    access_repo, source_type: SourceType, user_id: int, entity_id: int
) -> tuple[bool, int]:
    async with db.get_async_session() as session:
        removed = await access_repo.remove_access(user_id, entity_id, session=session)
        if not removed:
            return False, 0
        revoked = await ma_repo.remove_access_by_source(
            user_id, source_type, entity_id, session=session
        )
        return True, revoked


async def share_playlist_with_users(
    user_ids: list[int], playlist_id: int, media_ids: list[int]
) -> int:
    """Grant PlaylistAccess plus playlist-sourced MediaAccess atomically.

    Returns the number of MediaAccess rows inserted (existing rows are skipped).
    """
    return await _share_with_users(pa_repo, SourceType.PLAYLIST, user_ids, playlist_id, media_ids)


async def unshare_playlist_for_user(user_id: int, playlist_id: int) -> tuple[bool, int]:
    """Remove a user's PlaylistAccess row and playlist-sourced MediaAccess rows atomically.

    Returns (access_row_removed, media_rows_revoked). When the user has no
    PlaylistAccess row, nothing is deleted and (False, 0) is returned.
    """
    return await _unshare_for_user(pa_repo, SourceType.PLAYLIST, user_id, playlist_id)


async def share_subscription_with_users(
    user_ids: list[int], subscription_id: int, media_ids: list[int]
) -> int:
    """Grant SubscriptionAccess plus subscription-sourced MediaAccess atomically.

    Returns the number of MediaAccess rows inserted (existing rows are skipped).
    """
    return await _share_with_users(
        sa_repo, SourceType.SUBSCRIPTION, user_ids, subscription_id, media_ids
    )


async def unshare_subscription_for_user(user_id: int, subscription_id: int) -> tuple[bool, int]:
    """Remove a user's SubscriptionAccess row and subscription-sourced MediaAccess rows atomically.

    Returns (access_row_removed, media_rows_revoked). When the user has no
    SubscriptionAccess row, nothing is deleted and (False, 0) is returned.
    """
    return await _unshare_for_user(sa_repo, SourceType.SUBSCRIPTION, user_id, subscription_id)
