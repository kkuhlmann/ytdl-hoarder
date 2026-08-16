from database import db
from models import User
from repositories import ratings as ratings_repo


def _create_test_user(user_id=1):
    """Insert a test user directly so FK constraints are satisfied."""
    with db.sync_session() as session:
        session.add(
            User(id=user_id, username=f'testuser{user_id}', password_hash='x', is_approved=True)
        )


async def test_upsert_rating_create(test_database):
    """Create a new rating."""
    _create_test_user(1)
    rating = await ratings_repo.upsert_rating(user_id=1, media_details_id=1, rating=4)
    assert rating.rating == 4
    assert rating.user_id == 1
    assert rating.media_details_id == 1


async def test_upsert_rating_update(test_database):
    """Updating an existing rating changes the value in-place."""
    _create_test_user(1)
    await ratings_repo.upsert_rating(user_id=1, media_details_id=1, rating=3)
    updated = await ratings_repo.upsert_rating(user_id=1, media_details_id=1, rating=5)
    assert updated.rating == 5

    # Verify only one row exists
    ratings = await ratings_repo.get_ratings_for_media_ids(user_id=1, media_ids=[1])
    assert ratings == {1: 5}


async def test_delete_rating(test_database):
    _create_test_user(1)
    await ratings_repo.upsert_rating(user_id=1, media_details_id=1, rating=3)
    deleted = await ratings_repo.delete_rating(user_id=1, media_details_id=1)
    assert deleted is True

    ratings = await ratings_repo.get_ratings_for_media_ids(user_id=1, media_ids=[1])
    assert ratings == {}


async def test_delete_rating_nonexistent(test_database):
    deleted = await ratings_repo.delete_rating(user_id=1, media_details_id=1)
    assert deleted is False


async def test_get_ratings_for_media_ids_batch(test_database):
    """Batch fetch returns ratings keyed by media ID."""
    _create_test_user(1)
    await ratings_repo.upsert_rating(user_id=1, media_details_id=1, rating=5)
    await ratings_repo.upsert_rating(user_id=1, media_details_id=2, rating=2)

    result = await ratings_repo.get_ratings_for_media_ids(user_id=1, media_ids=[1, 2])
    assert result == {1: 5, 2: 2}


async def test_get_ratings_for_media_ids_empty(test_database):
    result = await ratings_repo.get_ratings_for_media_ids(user_id=1, media_ids=[])
    assert result == {}


async def test_ratings_are_per_user(test_database):
    """Each user has independent ratings."""
    _create_test_user(1)
    _create_test_user(2)
    await ratings_repo.upsert_rating(user_id=1, media_details_id=1, rating=5)
    await ratings_repo.upsert_rating(user_id=2, media_details_id=1, rating=1)

    user1 = await ratings_repo.get_ratings_for_media_ids(user_id=1, media_ids=[1])
    user2 = await ratings_repo.get_ratings_for_media_ids(user_id=2, media_ids=[1])
    assert user1 == {1: 5}
    assert user2 == {1: 1}
