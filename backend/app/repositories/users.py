from sqlalchemy import func
from sqlmodel import select

from database import db
from models import MediaDetails, TaskStatus, User, utc_now

# --- Async functions for FastAPI ---


async def get_user_count() -> int:
    async with db.get_async_session() as session:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(User)
        result = await session.execute(stmt)
        return result.scalar()


async def get_user_by_username(username: str) -> User | None:
    async with db.get_async_session() as session:
        stmt = select(User).where(User.username == username)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def create_user(user: User) -> User:
    async with db.get_async_session() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def get_user_by_id(user_id: int) -> User | None:
    async with db.get_async_session() as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def get_all_approved_users() -> list[User]:
    """Get all approved users, ordered by username."""
    async with db.get_async_session() as session:
        stmt = select(User).where(User.is_approved == True).order_by(User.username)  # noqa: E712
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def update_user(user_id: int, **kwargs) -> User | None:
    async with db.get_async_session() as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return None

        for key, value in kwargs.items():
            setattr(user, key, value)

        await session.commit()
        await session.refresh(user)
        return user


async def delete_user(user_id: int) -> bool:
    """Delete a user by ID. Returns True if deleted."""
    async with db.get_async_session() as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return False

        await session.delete(user)
        await session.commit()
        return True


async def get_user_storage_usage(user_id: int) -> int:
    """Get total file size of all COMPLETE media owned by a user.

    Only counts media where the user is the owner (owner_id), not shared media.
    """
    async with db.get_async_session() as session:
        stmt = select(func.coalesce(func.sum(MediaDetails.file_size_bytes), 0)).where(
            MediaDetails.owner_id == user_id,
            MediaDetails.status == TaskStatus.COMPLETE,
            MediaDetails.file_size_bytes.is_not(None),
        )
        result = await session.execute(stmt)
        return int(result.scalar())


# --- Sync functions (job bodies run in lane threads / the ML child) ---


def sync_get_user_by_id(user_id: int) -> User | None:
    with db.sync_session() as session:
        stmt = select(User).where(User.id == user_id)
        result = session.execute(stmt)
        return result.scalar_one_or_none()


def sync_get_user_by_username(username: str) -> User | None:
    with db.sync_session() as session:
        stmt = select(User).where(User.username == username)
        result = session.execute(stmt)
        return result.scalar_one_or_none()


def sync_set_password(user_id: int, password_hash: str) -> bool:
    """Set a user's password and clear any outstanding recovery state.

    Bumping password_changed_at invalidates tokens issued before now, so a reset
    performed from the CLI also signs the account out everywhere.
    """
    with db.sync_session() as session:
        stmt = select(User).where(User.id == user_id)
        user = session.execute(stmt).scalar_one_or_none()
        if not user:
            return False

        user.password_hash = password_hash
        user.password_changed_at = utc_now()
        user.must_change_password = False
        user.password_reset_requested_at = None
        user.recovery_code_hash = None
        user.recovery_code_expires_at = None
        session.commit()
        return True


def sync_get_user_storage_usage(user_id: int) -> int:
    """Sync version: Get total file size of all COMPLETE media owned by a user."""
    with db.sync_session() as session:
        stmt = select(func.coalesce(func.sum(MediaDetails.file_size_bytes), 0)).where(
            MediaDetails.owner_id == user_id,
            MediaDetails.status == TaskStatus.COMPLETE,
            MediaDetails.file_size_bytes.is_not(None),
        )
        result = session.execute(stmt)
        return int(result.scalar())
