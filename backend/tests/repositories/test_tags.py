from sqlalchemy import update

from database import db
from models import MediaDetails, MediaTag, TaskStatus, User
from repositories import tags as tags_repo


def _create_test_user(user_id=1):
    """Insert a test user directly so FK constraints are satisfied."""
    with db.sync_session() as session:
        session.add(
            User(id=user_id, username=f'testuser{user_id}', password_hash='x', is_approved=True)
        )


def _set_media_status(media_details_id, status):
    """Update a media item's status directly (mimics soft delete marking)."""
    with db.sync_session() as session:
        session.execute(
            update(MediaDetails).where(MediaDetails.id == media_details_id).values(status=status)
        )
        session.commit()


def _count_media_tags(media_details_id):
    """Count MediaTag rows for a media (all users)."""
    from sqlmodel import select

    with db.sync_session() as session:
        rows = session.execute(
            select(MediaTag).where(MediaTag.media_details_id == media_details_id)
        ).all()
        return len(rows)


async def test_get_user_tags_empty(test_database):
    """No tags exist initially."""
    result = await tags_repo.get_user_tags(user_id=999)
    assert result == []


async def test_get_or_create_tag(test_database):
    """Creates a new tag, then returns the existing one on second call."""
    _create_test_user(1)
    tag1 = await tags_repo.get_or_create_tag(user_id=1, name='  Favorite  ')
    assert tag1.name == 'favorite'  # normalized: stripped + lowercased
    assert tag1.user_id == 1

    tag2 = await tags_repo.get_or_create_tag(user_id=1, name='FAVORITE')
    assert tag2.id == tag1.id  # same tag returned


async def test_get_user_tags_only_returns_tags_with_live_media(test_database):
    """Only tags applied to a COMPLETE media are returned; unused tags are omitted."""
    _create_test_user(1)
    await tags_repo.get_or_create_tag(user_id=1, name='rock')
    await tags_repo.get_or_create_tag(user_id=1, name='jazz')  # never applied to any media
    # Assign 'rock' to media 1 (COMPLETE in the test fixture)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['rock'])

    result = await tags_repo.get_user_tags(user_id=1)
    assert len(result) == 1
    assert result[0]['name'] == 'rock'
    assert result[0]['usage_count'] == 1


async def test_get_user_tags_excludes_non_complete_media(test_database):
    """A tag whose only media is not COMPLETE (e.g. soft-deleted) is not returned."""
    _create_test_user(1)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['ghost'])
    assert len(await tags_repo.get_user_tags(user_id=1)) == 1

    # Soft delete marks the media DELETED (MediaTag rows may linger); tag must drop out.
    _set_media_status(1, TaskStatus.DELETED)
    assert await tags_repo.get_user_tags(user_id=1) == []


async def test_get_user_tags_excludes_untagged_last_media(test_database):
    """Removing the last tag from a media drops it from the dropdown (no deletion)."""
    _create_test_user(1)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['solo'])
    assert len(await tags_repo.get_user_tags(user_id=1)) == 1

    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=[])
    assert await tags_repo.get_user_tags(user_id=1) == []


async def test_remove_all_media_tags_for_media(test_database):
    """Soft-delete cleanup strips every user's tags from a media."""
    _create_test_user(1)
    _create_test_user(2)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['a', 'b'])
    await tags_repo.set_media_tags(user_id=2, media_details_id=1, tag_names=['c'])
    assert _count_media_tags(1) == 3

    removed = await tags_repo.remove_all_media_tags_for_media(media_details_id=1)
    assert removed == 3
    assert _count_media_tags(1) == 0
    assert await tags_repo.get_user_tags(user_id=1) == []
    assert await tags_repo.get_user_tags(user_id=2) == []


async def test_remove_user_media_tags_for_media_scoped(test_database):
    """Direct-access delete strips only the departing user's tags."""
    _create_test_user(1)
    _create_test_user(2)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['mine'])
    await tags_repo.set_media_tags(user_id=2, media_details_id=1, tag_names=['theirs'])

    removed = await tags_repo.remove_user_media_tags_for_media(user_id=1, media_details_id=1)
    assert removed == 1
    assert await tags_repo.get_user_tags(user_id=1) == []
    # User 2's tag on the same media is untouched
    user2_tags = await tags_repo.get_user_tags(user_id=2)
    assert [t['name'] for t in user2_tags] == ['theirs']


async def test_rename_tag(test_database):
    _create_test_user(1)
    tag = await tags_repo.get_or_create_tag(user_id=1, name='old')
    renamed = await tags_repo.rename_tag(user_id=1, tag_id=tag.id, new_name='  NEW  ')
    assert renamed is not None
    assert renamed.name == 'new'


async def test_rename_tag_collision(test_database):
    """Renaming to an existing name returns None."""
    _create_test_user(1)
    await tags_repo.get_or_create_tag(user_id=1, name='alpha')
    tag_b = await tags_repo.get_or_create_tag(user_id=1, name='beta')
    result = await tags_repo.rename_tag(user_id=1, tag_id=tag_b.id, new_name='alpha')
    assert result is None


async def test_rename_tag_wrong_user(test_database):
    _create_test_user(1)
    _create_test_user(2)
    tag = await tags_repo.get_or_create_tag(user_id=1, name='mine')
    result = await tags_repo.rename_tag(user_id=2, tag_id=tag.id, new_name='stolen')
    assert result is None


async def test_delete_tag(test_database):
    _create_test_user(1)
    tag = await tags_repo.get_or_create_tag(user_id=1, name='deleteme')
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['deleteme'])

    deleted = await tags_repo.delete_tag(user_id=1, tag_id=tag.id)
    assert deleted is True

    # Tag and associations gone
    tags = await tags_repo.get_user_tags(user_id=1)
    assert len(tags) == 0

    media_tags = await tags_repo.get_tags_for_media_ids(user_id=1, media_ids=[1])
    assert media_tags == {}


async def test_delete_tag_wrong_user(test_database):
    _create_test_user(1)
    _create_test_user(2)
    tag = await tags_repo.get_or_create_tag(user_id=1, name='mine')
    deleted = await tags_repo.delete_tag(user_id=2, tag_id=tag.id)
    assert deleted is False


async def test_set_media_tags(test_database):
    """set_media_tags creates missing tags and returns final list."""
    _create_test_user(1)
    result = await tags_repo.set_media_tags(
        user_id=1,
        media_details_id=1,
        tag_names=['rock', 'classic', 'rock'],  # duplicate
    )
    assert len(result) == 2
    names = [t['name'] for t in result]
    assert 'classic' in names
    assert 'rock' in names


async def test_set_media_tags_replaces_previous(test_database):
    """Calling set_media_tags replaces all previous tags."""
    _create_test_user(1)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['a', 'b', 'c'])
    result = await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['b', 'd'])
    names = [t['name'] for t in result]
    assert sorted(names) == ['b', 'd']


async def test_set_media_tags_empty_clears(test_database):
    """Empty list removes all tags."""
    _create_test_user(1)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['x'])
    result = await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=[])
    assert result == []


async def test_get_tags_for_media_ids_batch(test_database):
    """Batch fetch returns tags grouped by media ID."""
    _create_test_user(1)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['rock'])
    await tags_repo.set_media_tags(user_id=1, media_details_id=2, tag_names=['pop', 'dance'])

    result = await tags_repo.get_tags_for_media_ids(user_id=1, media_ids=[1, 2])
    assert len(result[1]) == 1
    assert result[1][0]['name'] == 'rock'
    assert len(result[2]) == 2


async def test_get_tags_for_media_ids_empty(test_database):
    result = await tags_repo.get_tags_for_media_ids(user_id=1, media_ids=[])
    assert result == {}


async def test_tags_are_per_user(test_database):
    """Tags created by one user are invisible to another."""
    _create_test_user(1)
    _create_test_user(2)
    await tags_repo.set_media_tags(user_id=1, media_details_id=1, tag_names=['private'])

    user1_tags = await tags_repo.get_user_tags(user_id=1)
    user2_tags = await tags_repo.get_user_tags(user_id=2)
    assert len(user1_tags) == 1
    assert len(user2_tags) == 0

    user2_media_tags = await tags_repo.get_tags_for_media_ids(user_id=2, media_ids=[1])
    assert user2_media_tags == {}
