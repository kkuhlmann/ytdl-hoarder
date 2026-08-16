from typing import Any

from sqlalchemy import and_, asc, delete, desc, func, or_
from sqlalchemy.orm import contains_eager
from sqlmodel import select

from database import db
from logger import logger
from models import (
    MediaAccess,
    MediaDetails,
    PlaybackState,
    Playlist,
    PlaylistAccess,
    PlaylistMedia,
    SourceType,
    utc_now,
)
from repositories.media_details import (
    _fetch_ratings_and_tags,
    _fetch_samples,
    _serialize_media_record,
)
from repositories.pagination import page_count

# --- Async functions for FastAPI ---


async def create_playlist(
    name: str,
    description: str | None = None,
    source_url: str | None = None,
    user_id: int | None = None,
) -> Playlist:
    async with db.get_async_session() as session:
        playlist = Playlist(
            name=name, description=description, source_url=source_url, user_id=user_id
        )
        session.add(playlist)
        await session.commit()
        await session.refresh(playlist)
        return playlist


async def get_playlist_by_id(id: int) -> Playlist | None:
    async with db.get_async_session() as session:
        stmt = select(Playlist).where(Playlist.id == id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def get_all_playlists(
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str | None = None,
    sort_direction: str = 'desc',
    user_id: int | None = None,
) -> dict[str, Any]:
    """Get all playlists with optional filtering and pagination.

    Args:
        user_id: When provided, filter to playlists owned by this user OR
                 shared via PlaylistAccess. When None, no user filter (admin view).

    Returns dict with count_records, page_count, and records (with media_count and total_duration).
    """
    async with db.get_async_session() as session:
        stmt = select(Playlist)
        conditions = []

        if user_id is not None:
            accessible_ids = select(PlaylistAccess.playlist_id).where(
                PlaylistAccess.user_id == user_id
            )
            conditions.append(or_(Playlist.user_id == user_id, Playlist.id.in_(accessible_ids)))

        if search:
            conditions.append(Playlist.name.ilike(f'%{search}%'))

        if conditions:
            stmt = stmt.where(and_(*conditions))

        count_stmt = select(func.count()).select_from(
            select(Playlist.id).where(and_(*conditions) if conditions else True).subquery()
        )
        count_result = await session.execute(count_stmt)
        count_records = count_result.scalar()

        if sort_by and hasattr(Playlist, sort_by):
            sort_column = getattr(Playlist, sort_by)
            if sort_direction == 'asc':
                stmt = stmt.order_by(asc(sort_column).nullsfirst(), Playlist.id.asc())
            else:
                stmt = stmt.order_by(desc(sort_column).nullslast(), Playlist.id.desc())
        else:
            stmt = stmt.order_by(Playlist.created_at.desc())

        if page_size is not None:
            stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await session.execute(stmt)
        records = result.scalars().all()

        # One grouped query for the whole page's stats (avoids N+1 per playlist)
        playlist_ids = [p.id for p in records]
        stats_by_id = await _get_stats_for_playlists(session, playlist_ids)

        # First four tracks per playlist, for the grid view's collage. Same
        # window-function helper the media library's group folders use.
        samples_by_id = await _fetch_samples(
            session,
            PlaylistMedia.playlist_id,
            [PlaylistMedia.playlist_id.in_(playlist_ids)] if playlist_ids else [],
            playlist_ids,
            joins=[(PlaylistMedia, PlaylistMedia.media_details_id == MediaDetails.id)],
            order_by=(PlaylistMedia.position.asc(),),
        )

        serialized_records = []
        for playlist in records:
            record_dict = playlist.model_dump(mode='json')

            stats = stats_by_id.get(playlist.id, {'media_count': 0, 'total_duration': 0})
            record_dict['media_count'] = stats['media_count']
            record_dict['total_duration'] = stats['total_duration']
            record_dict['sample_media_ids'] = samples_by_id.get(playlist.id, [])

            serialized_records.append(record_dict)

        return {
            'count_records': count_records,
            'page_count': page_count(count_records, page_size),
            'records': serialized_records,
        }


async def update_playlist(id: int, updated_params: dict) -> Playlist | None:
    async with db.get_async_session() as session:
        stmt = select(Playlist).where(Playlist.id == id)
        result = await session.execute(stmt)
        playlist = result.scalar_one_or_none()

        if not playlist:
            return None

        for key, value in updated_params.items():
            if hasattr(playlist, key) and key not in ('id', 'created_at'):
                setattr(playlist, key, value)

        playlist.updated_at = utc_now()
        await session.commit()
        await session.refresh(playlist)
        return playlist


async def delete_playlist(id: int) -> int:
    """Delete a playlist and its media associations (cascade).

    Also cleans up all playlist-sourced MediaAccess rows atomically in the same
    transaction, so shared users lose access when the playlist is deleted.

    Returns number of records deleted (0 or 1).
    """
    async with db.get_async_session() as session:
        stmt = select(Playlist).where(Playlist.id == id)
        result = await session.execute(stmt)
        playlist = result.scalar_one_or_none()

        if not playlist:
            return 0

        cleanup_stmt = delete(MediaAccess).where(
            MediaAccess.source_type == SourceType.PLAYLIST,
            MediaAccess.source_id == id,
        )
        cleanup_result = await session.execute(cleanup_stmt)
        if cleanup_result.rowcount > 0:
            logger.info(
                f'Cleaned up {cleanup_result.rowcount} playlist-sourced media_access rows '
                f'for playlist {id}'
            )

        # Clean up PlaylistAccess rows (normally CASCADE'd by FK, but explicit for safety)
        pa_cleanup = delete(PlaylistAccess).where(PlaylistAccess.playlist_id == id)
        await session.execute(pa_cleanup)

        await session.delete(playlist)
        await session.commit()
        logger.info(f'Deleted playlist with id: {id}')
        return 1


async def add_media_to_playlist(
    playlist_id: int, media_details_id: int, position: int | None = None
) -> PlaylistMedia | None:
    """Add media to a playlist at the specified position.

    If position is None, appends to the end.
    Returns the created PlaylistMedia or None if playlist/media doesn't exist.
    """
    async with db.get_async_session() as session:
        # Verify playlist exists (keep the row so we can bump updated_at without a lock)
        playlist = (
            await session.execute(select(Playlist).where(Playlist.id == playlist_id))
        ).scalar_one_or_none()
        if not playlist:
            return None

        media_stmt = select(MediaDetails).where(MediaDetails.id == media_details_id)
        media_result = await session.execute(media_stmt)
        if not media_result.scalar_one_or_none():
            return None

        existing_stmt = select(PlaylistMedia).where(
            and_(
                PlaylistMedia.playlist_id == playlist_id,
                PlaylistMedia.media_details_id == media_details_id,
            )
        )
        existing_result = await session.execute(existing_stmt)
        if existing_result.scalar_one_or_none():
            logger.info(f'Media {media_details_id} already in playlist {playlist_id}')
            return None

        if position is None:
            position = await _get_next_position(session, playlist_id)

        await _shift_positions(session, playlist_id, position, 1)

        playlist_media = PlaylistMedia(
            playlist_id=playlist_id,
            media_details_id=media_details_id,
            position=position,
        )
        session.add(playlist_media)

        # Update playlist's updated_at (no lock needed; matches add_media_bulk)
        playlist.updated_at = utc_now()

        await session.commit()
        await session.refresh(playlist_media)
        return playlist_media


async def add_media_bulk(playlist_id: int, media_details_ids: list[int]) -> dict | None:
    """Add multiple media to a playlist in a single transaction (append at end).

    De-duplicates the input, skips media already in the playlist or that don't
    exist, and assigns sequential positions from one MAX(position) read — so
    there is no per-item position race. Returns a summary dict, or None if the
    playlist doesn't exist.
    """
    async with db.get_async_session() as session:
        playlist = (
            await session.execute(select(Playlist).where(Playlist.id == playlist_id))
        ).scalar_one_or_none()
        if not playlist:
            return None

        seen: set[int] = set()
        ordered_ids = [mid for mid in media_details_ids if not (mid in seen or seen.add(mid))]

        existing_ids = set(
            (
                await session.execute(
                    select(PlaylistMedia.media_details_id).where(
                        PlaylistMedia.playlist_id == playlist_id
                    )
                )
            ).scalars()
        )

        valid_ids: set[int] = set()
        if ordered_ids:
            valid_ids = set(
                (
                    await session.execute(
                        select(MediaDetails.id).where(MediaDetails.id.in_(ordered_ids))
                    )
                ).scalars()
            )

        to_add = [mid for mid in ordered_ids if mid in valid_ids and mid not in existing_ids]

        base_position = await _get_next_position(session, playlist_id)
        session.add_all(
            [
                PlaylistMedia(
                    playlist_id=playlist_id,
                    media_details_id=mid,
                    position=base_position + i,
                )
                for i, mid in enumerate(to_add)
            ]
        )

        if to_add:
            playlist.updated_at = utc_now()

        await session.commit()

        logger.info(
            f'Bulk-added {len(to_add)} media to playlist {playlist_id} '
            f'(requested {len(ordered_ids)} unique)'
        )
        return {
            'added': len(to_add),
            'already_present': sum(1 for mid in ordered_ids if mid in existing_ids),
            'invalid': sum(1 for mid in ordered_ids if mid not in valid_ids),
            'added_media_ids': to_add,
        }


async def remove_media_from_playlist(playlist_id: int, media_details_id: int) -> int:
    """Remove media from a playlist.

    Returns number of records deleted (0 or 1).
    """
    async with db.get_async_session() as session:
        stmt = select(PlaylistMedia).where(
            and_(
                PlaylistMedia.playlist_id == playlist_id,
                PlaylistMedia.media_details_id == media_details_id,
            )
        )
        result = await session.execute(stmt)
        playlist_media = result.scalar_one_or_none()

        if not playlist_media:
            return 0

        await session.delete(playlist_media)
        await session.flush()
        await _renumber_positions(session, playlist_id)

        playlist_stmt = select(Playlist).where(Playlist.id == playlist_id)
        playlist_result = await session.execute(playlist_stmt)
        playlist = playlist_result.scalar_one_or_none()
        if playlist:
            playlist.updated_at = utc_now()

        await session.commit()
        return 1


async def remove_media_bulk(playlist_id: int, media_details_ids: list[int]) -> int:
    """Remove several media from a playlist in one transaction.

    Returns the number of associations removed. Positions are renumbered once at
    the end rather than shifted per removal.
    """
    if not media_details_ids:
        return 0

    async with db.get_async_session() as session:
        stmt = select(PlaylistMedia).where(
            and_(
                PlaylistMedia.playlist_id == playlist_id,
                PlaylistMedia.media_details_id.in_(media_details_ids),
            )
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return 0

        for pm in rows:
            await session.delete(pm)
        await session.flush()

        await _renumber_positions(session, playlist_id)

        playlist_stmt = select(Playlist).where(Playlist.id == playlist_id)
        playlist_result = await session.execute(playlist_stmt)
        playlist = playlist_result.scalar_one_or_none()
        if playlist:
            playlist.updated_at = utc_now()

        await session.commit()
        logger.info(f'Bulk-removed {len(rows)} media from playlist {playlist_id}')
        return len(rows)


async def remove_media_from_all_playlists(media_details_id: int) -> int:
    """Remove a media item from every playlist it belongs to.

    For each affected playlist, shifts remaining positions down and updates updated_at.
    Returns the number of playlist associations removed.
    """
    async with db.get_async_session() as session:
        stmt = select(PlaylistMedia).where(PlaylistMedia.media_details_id == media_details_id)
        result = await session.execute(stmt)
        playlist_media_rows = result.scalars().all()

        if not playlist_media_rows:
            return 0

        affected_playlists: dict[int, list[int]] = {}
        for pm in playlist_media_rows:
            affected_playlists.setdefault(pm.playlist_id, []).append(pm.position)

        for pm in playlist_media_rows:
            await session.delete(pm)

        now = utc_now()
        for playlist_id, positions in affected_playlists.items():
            # Process from lowest position to avoid conflicts
            for position in sorted(positions):
                await _shift_positions(session, playlist_id, position + 1, -1)

            playlist_stmt = select(Playlist).where(Playlist.id == playlist_id)
            playlist_result = await session.execute(playlist_stmt)
            playlist = playlist_result.scalar_one_or_none()
            if playlist:
                playlist.updated_at = now

        await session.commit()
        return len(playlist_media_rows)


async def get_playlist_media(
    playlist_id: int,
    page: int = 1,
    page_size: int | None = None,
    user_id: int | None = None,
    sort_by: str = 'position',
    sort_direction: str = 'asc',
    light: bool = False,
    include_playback: bool = False,
) -> dict[str, Any]:
    """Get media in a playlist, at media-library parity.

    Each record is the full serialized MediaDetails (ratings, tags, playback
    state, transcript progress) merged with the join fields, so a playlist track
    renders with exactly the same components as a media library row.

    Args:
        user_id: Whose ratings/tags/playback state to attach. None omits them.
        sort_by: 'position' (default), 'added_at', or any MediaDetails column.
        light: Skip the per-user enrichment (ratings, tags, playback state).
            The media player fetches whole playlists (page_size=1000) on every
            play click and reads only the basic fields — without this, the app's
            most common interaction pays for lookups it never uses.
        include_playback: Attach playback state even under `light`, for a queue
            that resumes each track. Kept separate from `light` so a playlist
            that doesn't resume still pays nothing: this is one flat indexed
            SELECT, where ratings and tags are two queries and a join.

    Returns dict with count_records, page_count, and records.
    """
    async with db.get_async_session() as session:
        # Explicit join rather than joinedload: joinedload aliases media_details,
        # and an ORDER BY on a MediaDetails column would then reference a table
        # that isn't in the FROM clause. contains_eager reuses this same join to
        # populate the relationship, so it stays one query either way.
        stmt = (
            select(PlaylistMedia)
            .outerjoin(MediaDetails, MediaDetails.id == PlaylistMedia.media_details_id)
            .where(PlaylistMedia.playlist_id == playlist_id)
            .options(contains_eager(PlaylistMedia.media_details))
        )

        # The task records are eager-loaded even in light mode: the shared
        # serializer reads these relationships unconditionally, and under async
        # SQLAlchemy an unloaded relationship raises rather than lazy-loading.
        # They're two LEFT JOINs on an indexed FK in the query we already run —
        # what light mode actually saves is the per-user round trips below.
        stmt = stmt.options(
            contains_eager(PlaylistMedia.media_details).joinedload(
                MediaDetails.transcript_task_record
            ),
            contains_eager(PlaylistMedia.media_details).joinedload(
                MediaDetails.download_task_record
            ),
        )

        stmt = _apply_media_sort(stmt, sort_by, sort_direction)

        count_stmt = select(func.count()).select_from(
            select(PlaylistMedia.id).where(PlaylistMedia.playlist_id == playlist_id).subquery()
        )
        count_result = await session.execute(count_stmt)
        count_records = count_result.scalar()

        if page_size is not None:
            stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await session.execute(stmt)
        records = result.unique().scalars().all()

        media_ids = [pm.media_details_id for pm in records]

        playback_map: dict[int, dict] = {}
        ratings_map: dict[int, int] = {}
        tags_map: dict[int, list[dict]] = {}
        if user_id is not None and media_ids:
            if not light:
                ratings_map, tags_map = await _fetch_ratings_and_tags(session, media_ids, user_id)
            if not light or include_playback:
                playback_map = await _fetch_playback_state(session, media_ids, user_id)

        serialized_records = []
        for pm in records:
            if pm.media_details:
                record_dict = _serialize_media_record(
                    pm.media_details,
                    playback_data=playback_map.get(pm.media_details_id, {}),
                    rating=ratings_map.get(pm.media_details_id),
                    tags=tags_map.get(pm.media_details_id, []),
                )
            else:
                record_dict = {}

            # Join fields. The PK is emitted as playlist_media_id, not id:
            # `id` means media_details.id everywhere else on the client, and
            # conflating the two is the likeliest bug in this shape.
            record_dict['media_details_id'] = pm.media_details_id
            record_dict['playlist_media_id'] = pm.id
            record_dict['playlist_id'] = pm.playlist_id
            record_dict['position'] = pm.position
            record_dict['added_at'] = pm.added_at.isoformat() if pm.added_at else None

            serialized_records.append(record_dict)

        return {
            'count_records': count_records,
            'page_count': page_count(count_records, page_size),
            'records': serialized_records,
        }


def _apply_media_sort(stmt, sort_by: str, sort_direction: str):
    """Order playlist tracks by a join column or any MediaDetails column."""
    descending = sort_direction == 'desc'

    if sort_by == 'added_at':
        column = PlaylistMedia.added_at
    elif sort_by and sort_by != 'position' and hasattr(MediaDetails, sort_by):
        column = getattr(MediaDetails, sort_by)
    else:
        # Playlist order is the default and the only one reordering applies to.
        return stmt.order_by(
            PlaylistMedia.position.desc() if descending else PlaylistMedia.position.asc()
        )

    ordered = desc(column).nullslast() if descending else asc(column).nullsfirst()
    # Stable tiebreak so pagination can't drop or repeat a row.
    return stmt.order_by(ordered, PlaylistMedia.position.asc())


async def _fetch_playback_state(session, media_ids: list[int], user_id: int) -> dict[int, dict]:
    """Per-user playback position/last-accessed/access-count for a page."""
    if not media_ids:
        return {}
    stmt = select(
        PlaybackState.media_details_id,
        PlaybackState.playback_position,
        PlaybackState.last_accessed,
        PlaybackState.access_count,
    ).where(
        and_(
            PlaybackState.user_id == user_id,
            PlaybackState.media_details_id.in_(media_ids),
        )
    )
    result = await session.execute(stmt)
    return {
        row.media_details_id: {
            'playback_position': row.playback_position,
            'last_accessed': row.last_accessed,
            'access_count': row.access_count,
        }
        for row in result
    }


async def reorder_media(playlist_id: int, media_details_id: int, new_position: int) -> bool:
    """Move a media item to a new position within the playlist.

    Returns True if successful, False if media not in playlist.
    """
    async with db.get_async_session() as session:
        stmt = select(PlaylistMedia).where(
            and_(
                PlaylistMedia.playlist_id == playlist_id,
                PlaylistMedia.media_details_id == media_details_id,
            )
        )
        result = await session.execute(stmt)
        playlist_media = result.scalar_one_or_none()

        if not playlist_media:
            return False

        old_position = playlist_media.position

        if old_position == new_position:
            return True

        if old_position < new_position:
            # Moving down: shift items in between up
            shift_stmt = select(PlaylistMedia).where(
                and_(
                    PlaylistMedia.playlist_id == playlist_id,
                    PlaylistMedia.position > old_position,
                    PlaylistMedia.position <= new_position,
                )
            )
            shift_result = await session.execute(shift_stmt)
            for pm in shift_result.scalars():
                pm.position -= 1
        else:
            # Moving up: shift items in between down
            shift_stmt = select(PlaylistMedia).where(
                and_(
                    PlaylistMedia.playlist_id == playlist_id,
                    PlaylistMedia.position >= new_position,
                    PlaylistMedia.position < old_position,
                )
            )
            shift_result = await session.execute(shift_stmt)
            for pm in shift_result.scalars():
                pm.position += 1

        playlist_media.position = new_position

        playlist_stmt = select(Playlist).where(Playlist.id == playlist_id)
        playlist_result = await session.execute(playlist_stmt)
        playlist = playlist_result.scalar_one_or_none()
        if playlist:
            playlist.updated_at = utc_now()

        await session.commit()
        return True


async def get_playlist_stats(playlist_id: int) -> dict[str, Any]:
    """Get statistics for a playlist.

    Returns dict with media_count and total_duration.
    """
    async with db.get_async_session() as session:
        count_stmt = select(func.count()).select_from(
            select(PlaylistMedia.id).where(PlaylistMedia.playlist_id == playlist_id).subquery()
        )
        count_result = await session.execute(count_stmt)
        media_count = count_result.scalar() or 0

        duration_stmt = (
            select(func.sum(MediaDetails.duration))
            .select_from(PlaylistMedia)
            .join(MediaDetails)
            .where(PlaylistMedia.playlist_id == playlist_id)
        )
        duration_result = await session.execute(duration_stmt)
        total_duration = duration_result.scalar() or 0

        return {
            'media_count': media_count,
            'total_duration': total_duration,
        }


async def _get_stats_for_playlists(session, playlist_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Get media_count and total_duration for many playlists in one grouped query.

    Matches get_playlist_stats semantics exactly: media_count counts PlaylistMedia
    rows regardless of whether MediaDetails exists; total_duration sums only joined
    MediaDetails.duration (LEFT JOIN — missing rows and NULL durations add nothing).
    Playlists with no media are absent from the result; callers supply the 0/0 default.
    """
    if not playlist_ids:
        return {}

    stmt = (
        select(
            PlaylistMedia.playlist_id,
            func.count().label('media_count'),
            func.coalesce(func.sum(MediaDetails.duration), 0).label('total_duration'),
        )
        .select_from(PlaylistMedia)
        .outerjoin(MediaDetails, MediaDetails.id == PlaylistMedia.media_details_id)
        .where(PlaylistMedia.playlist_id.in_(playlist_ids))
        .group_by(PlaylistMedia.playlist_id)
    )
    result = await session.execute(stmt)
    return {
        row.playlist_id: {'media_count': row.media_count, 'total_duration': row.total_duration}
        for row in result.all()
    }


async def get_playlist_ids_for_media(
    media_details_id: int, user_id: int | None = None
) -> list[int]:
    """Get all playlist IDs that contain a given media item.

    Args:
        media_details_id: The media item to look up.
        user_id: When provided, filter to playlists owned by or shared with this user.
                 When None, no user filter (admin view).

    Returns list of playlist IDs.
    """
    async with db.get_async_session() as session:
        conditions = [PlaylistMedia.media_details_id == media_details_id]

        if user_id is not None:
            accessible_ids = select(PlaylistAccess.playlist_id).where(
                PlaylistAccess.user_id == user_id
            )
            conditions.append(or_(Playlist.user_id == user_id, Playlist.id.in_(accessible_ids)))

        stmt = (
            select(PlaylistMedia.playlist_id)
            .join(Playlist, PlaylistMedia.playlist_id == Playlist.id)
            .where(and_(*conditions))
        )

        result = await session.execute(stmt)
        return [row[0] for row in result.all()]


async def get_playlist_media_ids(playlist_id: int) -> list[int]:
    async with db.get_async_session() as session:
        stmt = select(PlaylistMedia.media_details_id).where(
            PlaylistMedia.playlist_id == playlist_id
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]


async def _get_next_position(session, playlist_id: int) -> int:
    """Get the next position for a new item in the playlist.

    Reuses the caller's session so the MAX(position) read and the subsequent
    insert happen in the same transaction (avoids the nested-session race).
    """
    stmt = select(func.max(PlaylistMedia.position)).where(PlaylistMedia.playlist_id == playlist_id)
    result = await session.execute(stmt)
    return (result.scalar() or 0) + 1


async def _renumber_positions(session, playlist_id: int):
    """Rewrite positions as a contiguous 1..N in current order.

    Contiguity is load-bearing: the client disables a track's move-up arrow when
    position == 1 and move-down when position == total, so a gap would strand a
    row. This is the single owner of that invariant — every removal path goes
    through it rather than shifting positions itself.
    """
    stmt = (
        select(PlaylistMedia)
        .where(PlaylistMedia.playlist_id == playlist_id)
        .order_by(PlaylistMedia.position.asc())
    )
    result = await session.execute(stmt)
    for index, pm in enumerate(result.scalars(), start=1):
        if pm.position != index:
            pm.position = index


async def _shift_positions(session, playlist_id: int, from_position: int, delta: int):
    stmt = select(PlaylistMedia).where(
        and_(
            PlaylistMedia.playlist_id == playlist_id,
            PlaylistMedia.position >= from_position,
        )
    )
    result = await session.execute(stmt)
    for pm in result.scalars():
        pm.position += delta


# --- Sync functions (job bodies run in lane threads / the ML child) ---


def sync_create_playlist(
    name: str,
    description: str | None = None,
    source_url: str | None = None,
    user_id: int | None = None,
) -> Playlist:
    with db.sync_session() as session:
        playlist = Playlist(
            name=name, description=description, source_url=source_url, user_id=user_id
        )
        session.add(playlist)
        session.flush()
        session.refresh(playlist)
        return playlist


def sync_get_playlist_by_source_url(source_url: str) -> Playlist | None:
    with db.sync_session() as session:
        stmt = select(Playlist).where(Playlist.source_url == source_url)
        result = session.execute(stmt)
        return result.scalar_one_or_none()


def sync_add_media_to_playlist(
    playlist_id: int, media_details_id: int, position: int | None = None
) -> PlaylistMedia | None:
    with db.sync_session() as session:
        playlist_stmt = select(Playlist).where(Playlist.id == playlist_id)
        playlist_result = session.execute(playlist_stmt)
        if not playlist_result.scalar_one_or_none():
            return None

        media_stmt = select(MediaDetails).where(MediaDetails.id == media_details_id)
        media_result = session.execute(media_stmt)
        if not media_result.scalar_one_or_none():
            return None

        existing_stmt = select(PlaylistMedia).where(
            and_(
                PlaylistMedia.playlist_id == playlist_id,
                PlaylistMedia.media_details_id == media_details_id,
            )
        )
        existing_result = session.execute(existing_stmt)
        if existing_result.scalar_one_or_none():
            logger.info(f'Media {media_details_id} already in playlist {playlist_id}')
            return None

        if position is None:
            position = sync_get_next_position(playlist_id)

        playlist_media = PlaylistMedia(
            playlist_id=playlist_id,
            media_details_id=media_details_id,
            position=position,
        )
        session.add(playlist_media)
        session.flush()
        session.refresh(playlist_media)
        return playlist_media


def sync_get_next_position(playlist_id: int) -> int:
    with db.sync_session() as session:
        stmt = select(func.max(PlaylistMedia.position)).where(
            PlaylistMedia.playlist_id == playlist_id
        )
        result = session.execute(stmt)
        max_position = result.scalar()
        return (max_position or 0) + 1
