"""Factory for generating entity-access repository functions.

Subscription, Playlist, and Clip access repositories are structurally identical —
the only differences are the access model class, the FK column name, and the entity
label used in error messages. This module generates all shared logic once so each
wrapper file becomes a thin binding of names.
"""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from database import db
from models import utc_now


@dataclass(frozen=True)
class AccessFunctions:
    add_access: Any
    add_access_bulk: Any
    remove_access: Any
    has_access: Any
    get_users_with_access: Any
    check_access_or_raise: Any
    check_owner_or_raise: Any
    sync_get_users_with_access: Any


def create_access_functions(  # noqa: C901 — a factory whose complexity is the sum of the closures it builds, not one flow
    access_model, fk_column_attr: str, entity_label: str
) -> AccessFunctions:
    """Generate a full set of access-control functions for a given entity type.

    Args:
        access_model: The SQLModel access table class (e.g. SubscriptionAccess).
        fk_column_attr: The attribute name of the FK column on that model (e.g. 'subscription_id').
        entity_label: Human-readable label for error messages (e.g. 'Subscription').
    """
    fk_column = getattr(access_model, fk_column_attr)

    async def add_access(user_id: int, entity_id: int):
        """Grant a user access to an entity. Idempotent (no-op if already exists)."""
        async with db.get_async_session() as session:
            stmt = select(access_model).where(
                access_model.user_id == user_id,
                fk_column == entity_id,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                return existing

            access = access_model(user_id=user_id, **{fk_column_attr: entity_id})
            session.add(access)
            await session.commit()
            await session.refresh(access)
            return access

    async def add_access_bulk(
        user_ids: list[int], entity_id: int, session: AsyncSession | None = None
    ) -> int:
        """Grant many users access to an entity in a single INSERT.

        Skips rows that already exist (ON CONFLICT DO NOTHING on the
        (user_id, fk) unique constraint). Returns rows actually inserted.
        When `session` is provided, joins the caller's transaction.
        """
        deduped = list(dict.fromkeys(user_ids))
        if not deduped:
            return 0
        rows = [
            {'user_id': uid, fk_column_attr: entity_id, 'created_at': utc_now()} for uid in deduped
        ]
        stmt = (
            pg_insert(access_model)
            .values(rows)
            .on_conflict_do_nothing(index_elements=['user_id', fk_column_attr])
            .returning(access_model.id)
        )
        async with db.use_async_session(session) as s:
            result = await s.execute(stmt)
            return len(result.scalars().all())

    async def remove_access(
        user_id: int, entity_id: int, session: AsyncSession | None = None
    ) -> bool:
        """Remove a user's access to an entity. Returns True if removed."""
        async with db.use_async_session(session) as s:
            stmt = select(access_model).where(
                access_model.user_id == user_id,
                fk_column == entity_id,
            )
            result = await s.execute(stmt)
            access = result.scalar_one_or_none()

            if not access:
                return False

            await s.delete(access)
            return True

    async def has_access(user_id: int, entity_id: int) -> bool:
        """Check if a user has shared access to an entity (not ownership)."""
        async with db.get_async_session() as session:
            stmt = select(access_model).where(
                access_model.user_id == user_id,
                fk_column == entity_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def get_users_with_access(entity_id: int) -> list[int]:
        """Get list of user IDs that have shared access to an entity."""
        async with db.get_async_session() as session:
            stmt = select(access_model.user_id).where(fk_column == entity_id)
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    async def check_access_or_raise(user_id: int, entity: Any, is_admin: bool = False):
        """Check if a user can access an entity and raise HTTP 404 if denied.

        Access is granted if: user is admin, user is the owner, or user has an access row.
        """
        if is_admin:
            return
        if entity.user_id == user_id:
            return
        if await has_access(user_id, entity.id):
            return
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'{entity_label} with id {entity.id} not found',
        )

    async def check_owner_or_raise(user_id: int, entity: Any, is_admin: bool = False):
        """Check if a user owns an entity and raise HTTP 404 if not.

        Only owners and admins can modify entities.
        """
        if is_admin:
            return
        if entity.user_id == user_id:
            return
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'{entity_label} with id {entity.id} not found',
        )

    def sync_get_users_with_access(entity_id: int) -> list[int]:
        """Sync version: Get list of user IDs that have shared access to an entity."""
        with db.sync_session() as session:
            stmt = select(access_model.user_id).where(fk_column == entity_id)
            result = session.execute(stmt)
            return [row[0] for row in result.all()]

    return AccessFunctions(
        add_access=add_access,
        add_access_bulk=add_access_bulk,
        remove_access=remove_access,
        has_access=has_access,
        get_users_with_access=get_users_with_access,
        check_access_or_raise=check_access_or_raise,
        check_owner_or_raise=check_owner_or_raise,
        sync_get_users_with_access=sync_get_users_with_access,
    )
