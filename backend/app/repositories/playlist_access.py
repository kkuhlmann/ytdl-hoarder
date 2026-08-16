from models import PlaylistAccess
from repositories.base_access import create_access_functions

_fns = create_access_functions(
    access_model=PlaylistAccess,
    fk_column_attr='playlist_id',
    entity_label='Playlist',
)

add_access = _fns.add_access
add_access_bulk = _fns.add_access_bulk
remove_access = _fns.remove_access
has_access = _fns.has_access
get_users_with_access = _fns.get_users_with_access
check_playlist_access_or_raise = _fns.check_access_or_raise
check_playlist_owner_or_raise = _fns.check_owner_or_raise
