from models import SubscriptionAccess
from repositories.base_access import create_access_functions

_fns = create_access_functions(
    access_model=SubscriptionAccess,
    fk_column_attr='subscription_id',
    entity_label='Subscription',
)

add_access = _fns.add_access
add_access_bulk = _fns.add_access_bulk
remove_access = _fns.remove_access
has_access = _fns.has_access
get_users_with_access = _fns.get_users_with_access
check_subscription_access_or_raise = _fns.check_access_or_raise
check_subscription_owner_or_raise = _fns.check_owner_or_raise
sync_get_users_with_access = _fns.sync_get_users_with_access
