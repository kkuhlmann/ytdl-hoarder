"""Router-layer factory for the share/unshare/shared-users endpoint trio.

The router-side mirror of repositories/base_access.py: every shareable entity
exposes the same three endpoints (plus an optional bulk share) with identical
shapes; only the ownership check, the grant/revoke actions, and the response
id key differ.

`name` and `description` are passed to the decorators explicitly rather than
left to the endpoint's `__name__`/`__doc__`. FastAPI reads both when the route
is constructed — i.e. while the decorator runs — so a generated handler cannot
supply them by assignment afterwards. They are not cosmetic: `name` drives the
OpenAPI operationId and the summary shown per endpoint in the Swagger UI, and
`description` is that endpoint's API documentation.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, status

from dependencies import get_admin_override, get_entity_or_404, get_required_user_id
from schemas import BulkShareRequest, ShareRequest


@dataclass(frozen=True)
class SharingConfig:
    entity_name: str  # get_entity_or_404 display name, e.g. 'Playlist'
    noun: str  # wording in 404 details, e.g. 'playlist'
    id_key: str  # response/bulk-error key, e.g. 'playlist_id'
    get_by_id: Callable
    check_owner_or_raise: Callable
    grant: Callable[[list[int], int], Awaitable[None]]
    revoke: Callable[[int, int], Awaitable[bool]]
    list_user_ids: Callable[[int], Awaitable[list[int]]]
    # Prose wording, pluralized by suffixing 's'; defaults to `noun`. Media needs
    # both: it reads as 'media' in an id-bearing 404 but 'media item(s)' in a sentence.
    doc_noun: str | None = None
    # Handler-name plural, defaults to `noun` + 's'. Media is its own plural.
    plural_slug: str | None = None
    # Media bulk-share uses a different repo call than its single share; None
    # means bulk reuses `grant`.
    bulk_grant: Callable[[list[int], int], Awaitable[None]] | None = None
    # Second paragraph of the bulk-share docstring, e.g. the cascade it preserves.
    bulk_note: str = ''


def register_sharing_routes(router: APIRouter, cfg: SharingConfig, *, bulk: bool = True) -> None:
    doc_noun = cfg.doc_noun or cfg.noun
    plural_slug = cfg.plural_slug or f'{cfg.noun}s'

    async def _owned_entity(entity_id: int, user_id: int, is_admin_override: bool):
        return await get_entity_or_404(
            cfg.get_by_id,
            entity_id,
            cfg.entity_name,
            access_check=partial(cfg.check_owner_or_raise, user_id, is_admin=is_admin_override),
        )

    if bulk:
        bulk_description = (
            f'Share multiple {doc_noun}s with multiple users in one call. Only owner or admin.'
            + (f'\n\n{cfg.bulk_note}' if cfg.bulk_note else '')
        )

        @router.post(
            '/share/bulk',
            status_code=status.HTTP_201_CREATED,
            response_description=f'Share multiple {doc_noun}s with multiple users',
            response_model=dict,
            name=f'bulk_share_{plural_slug}',
            description=bulk_description,
        )
        async def bulk_share(
            bulk_req: BulkShareRequest,
            user_id: int = Depends(get_required_user_id),
            is_admin_override: bool = Depends(get_admin_override),
        ):
            shared_count = 0
            errors: list[dict] = []
            grant = cfg.bulk_grant or cfg.grant
            for entity_id in bulk_req.entity_ids:
                try:
                    await _owned_entity(entity_id, user_id, is_admin_override)
                except HTTPException:
                    errors.append({cfg.id_key: entity_id, 'error': 'not found or not owner'})
                    continue

                await grant(bulk_req.user_ids, entity_id)
                shared_count += len(bulk_req.user_ids)

            return {'shared_count': shared_count, 'errors': errors}

    @router.post(
        '/{id}/share',
        status_code=status.HTTP_201_CREATED,
        response_description=f'Share {cfg.noun} with another user',
        name=f'share_{cfg.noun}',
        description=(
            f'Share a {doc_noun} with another user. '
            f'Only owner or admin (with admin_view) can share.'
        ),
    )
    async def share_entity(
        id: int,
        share_req: ShareRequest,
        user_id: int = Depends(get_required_user_id),
        is_admin_override: bool = Depends(get_admin_override),
    ):
        await _owned_entity(id, user_id, is_admin_override)
        await cfg.grant([share_req.user_id], id)
        return {'status': 'shared', cfg.id_key: id, 'user_id': share_req.user_id}

    @router.delete(
        '/{id}/share/{target_user_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        response_description='Remove shared access for a user',
        name=f'unshare_{cfg.noun}',
        description=(
            f"Remove a user's shared access to a {doc_noun}. "
            f'Only owner or admin (with admin_view) can unshare.'
        ),
    )
    async def unshare_entity(
        id: int,
        target_user_id: int,
        user_id: int = Depends(get_required_user_id),
        is_admin_override: bool = Depends(get_admin_override),
    ):
        await _owned_entity(id, user_id, is_admin_override)
        removed = await cfg.revoke(target_user_id, id)
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f'User {target_user_id} does not have shared access to {cfg.noun} {id}',
            )
        return

    @router.get(
        '/{id}/shared-users',
        status_code=status.HTTP_200_OK,
        response_description='List of users with shared access',
        name='get_shared_users',
        description=(
            f'Get list of user IDs with shared access to a {doc_noun}. '
            f'Only owner or admin (with admin_view).'
        ),
    )
    async def shared_users(
        id: int,
        user_id: int = Depends(get_required_user_id),
        is_admin_override: bool = Depends(get_admin_override),
    ):
        await _owned_entity(id, user_id, is_admin_override)
        shared_user_ids = await cfg.list_user_ids(id)
        return {cfg.id_key: id, 'shared_user_ids': shared_user_ids}
