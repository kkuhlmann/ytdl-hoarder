from sqlalchemy import and_, delete
from sqlmodel import select

from database import db
from models import MediaRating, utc_now


async def upsert_rating(user_id: int, media_details_id: int, rating: int) -> MediaRating:
    async with db.get_async_session() as session:
        stmt = select(MediaRating).where(
            and_(
                MediaRating.user_id == user_id,
                MediaRating.media_details_id == media_details_id,
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.rating = rating
            existing.updated_at = utc_now()
            await session.commit()
            await session.refresh(existing)
            return existing

        mr = MediaRating(
            user_id=user_id,
            media_details_id=media_details_id,
            rating=rating,
        )
        session.add(mr)
        await session.commit()
        await session.refresh(mr)
        return mr


async def delete_rating(user_id: int, media_details_id: int) -> bool:
    """Remove a rating. Returns True if a rating was deleted."""
    async with db.get_async_session() as session:
        stmt = delete(MediaRating).where(
            and_(
                MediaRating.user_id == user_id,
                MediaRating.media_details_id == media_details_id,
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0


async def get_ratings_for_media_ids(user_id: int, media_ids: list[int]) -> dict[int, int]:
    """Batch fetch ratings for multiple media items. Returns dict[media_id, rating]."""
    if not media_ids:
        return {}

    async with db.get_async_session() as session:
        stmt = select(MediaRating.media_details_id, MediaRating.rating).where(
            and_(
                MediaRating.user_id == user_id,
                MediaRating.media_details_id.in_(media_ids),
            )
        )
        result = await session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}
