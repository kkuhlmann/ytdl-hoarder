"""FastAPI dependencies for authentication enforcement.

These are used with Depends() in route handlers to enforce auth requirements.
"""

from functools import partial

from fastapi import Depends, HTTPException, Request, status

from repositories import clip_access as ca_repo
from repositories import clips as clips_repo
from repositories import media_access as ma_repo
from repositories import media_details as md_repo
from repositories import playlist_access as pa_repo
from repositories import playlists as playlists_repo


def get_required_user_id(request: Request) -> int:
    """Return user_id or raise 401/403. Use for endpoints that require auth.

    Rejects unapproved accounts with 403: the admin-approval gate is enforced here,
    server-side, not just in the frontend. `is_approved` is resolved from the DB by
    the auth middleware, so revoking approval takes effect on the next request. A
    pending user still holds a valid token (so /me can report their pending state)
    but cannot reach any data endpoint.

    The same applies to a user holding an admin-issued temporary password: they are
    authenticated, but locked out of data endpoints until they choose a new one.
    """
    user_id = request.state.user_id
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Authentication required',
        )
    if not request.state.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Account pending admin approval',
        )
    if request.state.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Password change required',
        )
    return user_id


def get_admin_user_id(request: Request) -> int:
    """Return user_id or raise 401/403. Use for admin-only endpoints.

    `is_admin` is resolved from the DB by the auth middleware, so a demoted or deleted
    admin loses access on their next request rather than at token expiry.
    """
    user_id = request.state.user_id
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Authentication required',
        )
    if not request.state.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Admin access required',
        )
    if request.state.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Password change required',
        )
    return user_id


def get_effective_user_id(
    request: Request,
    admin_view: bool = False,
    user_id: int = Depends(get_required_user_id),
) -> int | None:
    """The query-layer access filter: None means no user filter (admin sees all)."""
    return None if (admin_view and request.state.is_admin) else user_id


def get_admin_override(request: Request, admin_view: bool = False) -> bool:
    """True when the caller is an admin who explicitly asked for the admin view."""
    return admin_view and request.state.is_admin


async def get_entity_or_404(
    fetch_fn,
    entity_id: int | str,
    entity_label: str,
    access_check=None,
):
    """Fetch an entity by ID, raise 404 if missing, then run optional access check.

    Args:
        fetch_fn: Async callable that takes entity_id and returns entity or None.
        entity_id: The ID to look up.
        entity_label: Human-readable name for error messages (e.g. 'Clip', 'Playlist').
        access_check: Optional async callable(entity) that raises HTTPException on failure.
    """
    entity = await fetch_fn(entity_id)
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'{entity_label} with id {entity_id} not found',
        )
    if access_check:
        await access_check(entity)
    return entity


def entity_access_dependency(fetch_fn, entity_label: str, check_fn):
    """Build a Depends() that fetches /{id}, 404s if missing, and runs the access check.

    entity_label is part of the 404 detail and differs per router ('Media' vs
    'MediaDetails') — preserve each router's existing label exactly.
    """

    async def dependency(request: Request, id: int, user_id: int = Depends(get_required_user_id)):
        return await get_entity_or_404(
            fetch_fn,
            id,
            entity_label,
            access_check=partial(check_fn, user_id, is_admin=request.state.is_admin),
        )

    return dependency


get_accessible_media = entity_access_dependency(
    md_repo.get_media_details_by_id, 'Media', ma_repo.check_access_or_raise
)
get_accessible_media_details = entity_access_dependency(
    md_repo.get_media_details_by_id, 'MediaDetails', ma_repo.check_access_or_raise
)
get_accessible_clip = entity_access_dependency(
    clips_repo.get_clip_by_id, 'Clip', ca_repo.check_clip_access_or_raise
)
get_accessible_playlist = entity_access_dependency(
    playlists_repo.get_playlist_by_id, 'Playlist', pa_repo.check_playlist_access_or_raise
)
