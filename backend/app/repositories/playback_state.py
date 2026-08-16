from sqlalchemy import and_
from sqlmodel import select

from database import db
from models import PlaybackState


async def get_playback_state(user_id: int, media_details_id: int) -> PlaybackState | None:
    async with db.get_async_session() as session:
        stmt = select(PlaybackState).where(
            and_(
                PlaybackState.user_id == user_id,
                PlaybackState.media_details_id == media_details_id,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def upsert_playback_state(
    user_id: int, media_details_id: int, update_data: dict
) -> PlaybackState:
    async with db.get_async_session() as session:
        stmt = select(PlaybackState).where(
            and_(
                PlaybackState.user_id == user_id,
                PlaybackState.media_details_id == media_details_id,
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in update_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await session.commit()
            await session.refresh(existing)
            return existing

        ps = PlaybackState(
            user_id=user_id,
            media_details_id=media_details_id,
            **update_data,
        )
        session.add(ps)
        await session.commit()
        await session.refresh(ps)
        return ps
