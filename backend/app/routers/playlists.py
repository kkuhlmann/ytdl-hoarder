from functools import partial
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from dependencies import (
    get_accessible_playlist,
    get_effective_user_id,
    get_entity_or_404,
    get_required_user_id,
)
from logger import logger
from models import SourceType
from repositories import media_access as ma_repo
from repositories import media_details as md_repo
from repositories import playlist_access as pa_repo
from repositories import playlists as playlists_repo
from repositories import settings as settings_repo
from repositories import sharing as sharing_repo
from routers.sharing_routes import SharingConfig, register_sharing_routes

router = APIRouter()


class PlaylistCreate(BaseModel):
    name: str
    description: str | None = None
    source_url: str | None = None


class PlaylistUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class AddMediaRequest(BaseModel):
    media_details_id: int
    position: int | None = None


class BulkAddMediaRequest(BaseModel):
    media_details_ids: list[int]


class BulkRemoveMediaRequest(BaseModel):
    media_details_ids: list[int]


class ReorderRequest(BaseModel):
    new_position: int


class PlaylistStats(BaseModel):
    media_count: int
    total_duration: float


@router.get(
    '',
    status_code=status.HTTP_200_OK,
    response_description='List of playlists',
)
async def get_all_playlists(
    search: str | None = None,
    page: int = 1,
    page_size: int | None = None,
    sort_by: str | None = None,
    sort_direction: str = 'desc',
    effective_user_id: int | None = Depends(get_effective_user_id),
) -> dict[str, Any]:
    """Get all playlists with optional filtering and pagination."""
    if page_size is None:
        settings = await settings_repo.get_settings()
        page_size = settings.download_table_page_size

    return await playlists_repo.get_all_playlists(
        search=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_direction=sort_direction,
        user_id=effective_user_id,
    )


@router.post(
    '',
    status_code=status.HTTP_201_CREATED,
    response_description='Create a new playlist',
)
async def create_playlist(
    playlist_request: PlaylistCreate, user_id: int = Depends(get_required_user_id)
):
    """Create a new playlist."""
    playlist = await playlists_repo.create_playlist(
        name=playlist_request.name,
        description=playlist_request.description,
        source_url=playlist_request.source_url,
        user_id=user_id,
    )
    logger.info(f'Created playlist: {playlist.name} (id={playlist.id})')
    return playlist


@router.get(
    '/containing/{media_details_id}',
    status_code=status.HTTP_200_OK,
    response_description='Playlist IDs containing the given media',
)
async def get_playlists_containing_media(
    media_details_id: int,
    effective_user_id: int | None = Depends(get_effective_user_id),
):
    """Get all playlist IDs that contain a given media item."""
    playlist_ids = await playlists_repo.get_playlist_ids_for_media(
        media_details_id, user_id=effective_user_id
    )
    return {'playlist_ids': playlist_ids}


@router.get(
    '/{id}',
    status_code=status.HTTP_200_OK,
    response_description='Playlist details',
)
async def get_playlist(id: int, playlist=Depends(get_accessible_playlist)):
    """Get a single playlist by ID."""
    stats = await playlists_repo.get_playlist_stats(id)
    response = playlist.model_dump(mode='json')
    response['media_count'] = stats['media_count']
    response['total_duration'] = stats['total_duration']
    return response


@router.patch(
    '/{id}',
    status_code=status.HTTP_200_OK,
    response_description='Updated playlist',
)
async def update_playlist(
    request: Request, id: int, update: PlaylistUpdate, user_id: int = Depends(get_required_user_id)
):
    """Update a playlist's name or description. Only owner or admin."""
    playlist = await get_entity_or_404(
        playlists_repo.get_playlist_by_id,
        id,
        'Playlist',
        access_check=partial(
            pa_repo.check_playlist_owner_or_raise, user_id, is_admin=request.state.is_admin
        ),
    )

    update_data = update.model_dump(exclude_unset=True)
    if not update_data:
        return playlist

    return await playlists_repo.update_playlist(id, update_data)


@router.delete(
    '/{id}',
    status_code=status.HTTP_204_NO_CONTENT,
    response_description='Playlist deleted successfully',
)
async def delete_playlist(
    request: Request,
    id: int,
    user_id: int = Depends(get_required_user_id),
    playlist=Depends(get_accessible_playlist),
):
    """Delete a playlist. Owner/admin = actual delete. Shared user = remove own access."""
    if playlist.user_id == user_id or request.state.is_admin:
        await playlists_repo.delete_playlist(id)
        return

    removed, revoked = await sharing_repo.unshare_playlist_for_user(user_id, id)
    if removed:
        if revoked > 0:
            logger.info(f'Revoked {revoked} playlist-sourced media_access rows for user {user_id}')
        return

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f'Playlist with id {id} not found',
    )


@router.get(
    '/{id}/media',
    status_code=status.HTTP_200_OK,
    response_description='Media in playlist',
    dependencies=[Depends(get_accessible_playlist)],
)
async def get_playlist_media(
    id: int,
    page: int = 1,
    page_size: int | None = None,
    sort_by: str = 'position',
    sort_direction: str = 'asc',
    light: bool = False,
    include_playback: bool = False,
    user_id: int = Depends(get_required_user_id),
):
    """Get media items in a playlist.

    Defaults to playlist order. `light=true` returns the basic fields only —
    used by the media player, which fetches a whole playlist per play click and
    doesn't read ratings, tags or transcript state. `include_playback=true` adds
    back the saved playback position, for a player queue that resumes each track.
    """
    if page_size is None:
        settings = await settings_repo.get_settings()
        page_size = settings.download_table_page_size

    return await playlists_repo.get_playlist_media(
        id,
        page=page,
        page_size=page_size,
        user_id=user_id,
        sort_by=sort_by,
        sort_direction=sort_direction,
        light=light,
        include_playback=include_playback,
    )


@router.post(
    '/{id}/media',
    status_code=status.HTTP_201_CREATED,
    response_description='Media added to playlist',
)
async def add_media_to_playlist(
    request_obj: Request,
    id: int,
    add_request: AddMediaRequest,
    user_id: int = Depends(get_required_user_id),
):
    """Add media to a playlist. Only owner or admin.

    The caller must also have access to the media being added — otherwise sharing
    the playlist would cascade MediaAccess rows for media the caller can't access.
    """
    await get_entity_or_404(
        playlists_repo.get_playlist_by_id,
        id,
        'Playlist',
        access_check=partial(
            pa_repo.check_playlist_owner_or_raise, user_id, is_admin=request_obj.state.is_admin
        ),
    )
    await get_entity_or_404(
        md_repo.get_media_details_by_id,
        add_request.media_details_id,
        'MediaDetails',
        access_check=partial(
            ma_repo.check_access_or_raise, user_id, is_admin=request_obj.state.is_admin
        ),
    )

    result = await playlists_repo.add_media_to_playlist(
        playlist_id=id,
        media_details_id=add_request.media_details_id,
        position=add_request.position,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Failed to add media to playlist (media may not exist or already in playlist)',
        )

    shared_user_ids = await pa_repo.get_users_with_access(id)
    await ma_repo.add_access_bulk(
        shared_user_ids,
        [add_request.media_details_id],
        source_type=SourceType.PLAYLIST,
        source_id=id,
    )
    if shared_user_ids:
        logger.info(
            f'Granted playlist-sourced media_access to {len(shared_user_ids)} shared users '
            f'for media {add_request.media_details_id} in playlist {id}'
        )

    logger.info(
        f'Added media {add_request.media_details_id} to playlist {id} at position {result.position}'
    )
    return result


@router.post(
    '/{id}/media/bulk',
    status_code=status.HTTP_201_CREATED,
    response_description='Media added to playlist in bulk',
    response_model=dict,
)
async def add_media_bulk_to_playlist(
    request_obj: Request,
    id: int,
    bulk_req: BulkAddMediaRequest,
    user_id: int = Depends(get_required_user_id),
):
    """Add multiple media to a playlist in a single transaction. Only owner or admin.

    Media the caller can't access are skipped (reported as no_access) so sharing the
    playlist can never cascade MediaAccess rows for media the caller can't access.
    """
    await get_entity_or_404(
        playlists_repo.get_playlist_by_id,
        id,
        'Playlist',
        access_check=partial(
            pa_repo.check_playlist_owner_or_raise, user_id, is_admin=request_obj.state.is_admin
        ),
    )

    allowed_ids: list[int] = []
    no_access = 0
    for media_id in bulk_req.media_details_ids:
        media = await md_repo.get_media_details_by_id(media_id)
        if media is None:
            allowed_ids.append(media_id)  # let the repo count it as invalid
        elif await ma_repo.user_can_access_media(
            user_id, media, is_admin=request_obj.state.is_admin
        ):
            allowed_ids.append(media_id)
        else:
            no_access += 1

    result = await playlists_repo.add_media_bulk(id, allowed_ids)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Playlist with id {id} not found',
        )

    added_media_ids = result['added_media_ids']
    if added_media_ids:
        shared_user_ids = await pa_repo.get_users_with_access(id)
        await ma_repo.add_access_bulk(
            shared_user_ids,
            added_media_ids,
            source_type=SourceType.PLAYLIST,
            source_id=id,
        )
        if shared_user_ids:
            logger.info(
                f'Granted playlist-sourced media_access to {len(shared_user_ids)} shared users '
                f'for {len(added_media_ids)} media in playlist {id}'
            )

    return {**result, 'no_access': no_access}


@router.delete(
    '/{id}/media/{media_id}',
    status_code=status.HTTP_204_NO_CONTENT,
    response_description='Media removed from playlist',
)
async def remove_media_from_playlist(
    request: Request, id: int, media_id: int, user_id: int = Depends(get_required_user_id)
):
    """Remove media from a playlist. Only owner or admin."""
    await get_entity_or_404(
        playlists_repo.get_playlist_by_id,
        id,
        'Playlist',
        access_check=partial(
            pa_repo.check_playlist_owner_or_raise, user_id, is_admin=request.state.is_admin
        ),
    )

    deleted_count = await playlists_repo.remove_media_from_playlist(id, media_id)
    if deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Media {media_id} not found in playlist {id}',
        )

    revoked = await ma_repo.remove_media_access_by_source(media_id, SourceType.PLAYLIST, id)
    if revoked > 0:
        logger.info(
            f'Revoked {revoked} playlist-sourced media_access rows for media {media_id} '
            f'from playlist {id}'
        )
    return


@router.post(
    '/{id}/media/bulk-remove',
    status_code=status.HTTP_200_OK,
    response_description='Media removed from playlist in bulk',
    response_model=dict,
)
async def remove_media_bulk_from_playlist(
    request: Request,
    id: int,
    bulk_req: BulkRemoveMediaRequest,
    user_id: int = Depends(get_required_user_id),
):
    """Remove multiple media from a playlist in one transaction. Only owner or admin.

    Positions are renumbered once afterwards, so they stay contiguous 1..N.
    """
    await get_entity_or_404(
        playlists_repo.get_playlist_by_id,
        id,
        'Playlist',
        access_check=partial(
            pa_repo.check_playlist_owner_or_raise, user_id, is_admin=request.state.is_admin
        ),
    )

    removed = await playlists_repo.remove_media_bulk(id, bulk_req.media_details_ids)

    # Mirror the single-remove path: playlist-sourced access dies with the entry
    for media_id in bulk_req.media_details_ids:
        await ma_repo.remove_media_access_by_source(media_id, SourceType.PLAYLIST, id)

    return {'removed': removed}


@router.patch(
    '/{id}/media/{media_id}/reorder',
    status_code=status.HTTP_200_OK,
    response_description='Media reordered',
)
async def reorder_media(
    request_obj: Request,
    id: int,
    media_id: int,
    reorder_req: ReorderRequest,
    user_id: int = Depends(get_required_user_id),
):
    """Change the position of a media item within a playlist. Only owner or admin."""
    await get_entity_or_404(
        playlists_repo.get_playlist_by_id,
        id,
        'Playlist',
        access_check=partial(
            pa_repo.check_playlist_owner_or_raise, user_id, is_admin=request_obj.state.is_admin
        ),
    )

    success = await playlists_repo.reorder_media(
        playlist_id=id,
        media_details_id=media_id,
        new_position=reorder_req.new_position,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Media {media_id} not found in playlist {id}',
        )

    return {'status': 'ok', 'new_position': reorder_req.new_position}


@router.get(
    '/{id}/stats',
    status_code=status.HTTP_200_OK,
    response_description='Playlist statistics',
    response_model=PlaylistStats,
    dependencies=[Depends(get_accessible_playlist)],
)
async def get_playlist_stats(id: int):
    """Get statistics for a playlist."""
    stats = await playlists_repo.get_playlist_stats(id)
    return PlaylistStats(**stats)


# --- Sharing endpoints ---


async def _grant_playlist(user_ids: list[int], playlist_id: int) -> None:
    # Grant playlist access + playlist-sourced media access in one transaction
    media_ids = await playlists_repo.get_playlist_media_ids(playlist_id)
    await sharing_repo.share_playlist_with_users(user_ids, playlist_id, media_ids)
    if media_ids:
        logger.info(
            f'Granted playlist-sourced media_access for {len(media_ids)} media items '
            f'to users {user_ids} via playlist {playlist_id}'
        )


async def _revoke_playlist(target_user_id: int, playlist_id: int) -> bool:
    # Remove playlist access + playlist-sourced media access in one transaction
    removed, revoked = await sharing_repo.unshare_playlist_for_user(target_user_id, playlist_id)
    if revoked > 0:
        logger.info(
            f'Revoked {revoked} playlist-sourced media_access rows for user {target_user_id} '
            f'from playlist {playlist_id}'
        )
    return removed


register_sharing_routes(
    router,
    SharingConfig(
        entity_name='Playlist',
        noun='playlist',
        id_key='playlist_id',
        get_by_id=playlists_repo.get_playlist_by_id,
        check_owner_or_raise=pa_repo.check_playlist_owner_or_raise,
        grant=_grant_playlist,
        revoke=_revoke_playlist,
        list_user_ids=pa_repo.get_users_with_access,
        bulk_note=(
            "Skips playlists the caller doesn't own (reported in errors) and preserves the\n"
            'per-playlist cascade that grants playlist-sourced media access.'
        ),
    ),
)
