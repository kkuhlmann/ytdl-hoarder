from models import ClipAccess
from repositories.base_access import create_access_functions

_fns = create_access_functions(
    access_model=ClipAccess,
    fk_column_attr='clip_id',
    entity_label='Clip',
)

add_access = _fns.add_access
remove_access = _fns.remove_access
has_access = _fns.has_access
get_users_with_access = _fns.get_users_with_access
check_clip_access_or_raise = _fns.check_access_or_raise
check_clip_owner_or_raise = _fns.check_owner_or_raise
