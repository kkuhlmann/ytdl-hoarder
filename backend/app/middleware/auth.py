"""Optional authentication middleware.

Reads the JWT cookie on every request and attaches user info to request.state.
Never rejects requests — unauthenticated users simply get request.state.user_id = None.
Enforcement is handled by FastAPI dependencies in dependencies.py.

Identity is resolved from the database on every authenticated request rather than
trusted from the token claims. The JWT proves *who* the caller is (a signed user_id);
`is_admin`, `is_approved`, `must_change_password`, and the account's continued existence
are always read fresh from the User row. This makes admin demotion, approval revocation,
and account deletion take effect immediately instead of lingering until the (30-day)
token expires.

Password changes are enforced the same way, via `User.password_changed_at`: a token
issued before the current password was set is treated as unauthenticated, so resetting
a password signs out sessions on other devices.
"""

from datetime import UTC

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from auth import decode_jwt_token
from models import User
from repositories import users as user_repo


def _token_predates_password_change(payload: dict, user: User) -> bool:
    """Whether this token was issued before the user's current password was set.

    Compared at full sub-second precision, since the endpoints that change a password
    write password_changed_at and then immediately mint the caller's replacement token:
    truncating to whole seconds would make that replacement look contemporaneous with
    the tokens it is supposed to displace.

    Tokens minted before the `iat` claim existed count as issued at epoch, so they
    survive only while the account has never had a password change.
    """
    if user.password_changed_at is None:
        return False
    changed_at = user.password_changed_at.replace(tzinfo=UTC).timestamp()
    return payload.get('iat', 0) < changed_at


class OptionalAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.user_id = None
        request.state.username = None
        request.state.is_admin = False
        request.state.is_approved = False
        request.state.must_change_password = False

        token = request.cookies.get('auth_token')
        if token:
            payload = decode_jwt_token(token)
            if payload:
                # Re-resolve from the DB; a deleted account leaves state cleared.
                user = await user_repo.get_user_by_id(payload['user_id'])
                if user and not _token_predates_password_change(payload, user):
                    request.state.user_id = user.id
                    request.state.username = user.username
                    request.state.is_admin = user.is_admin
                    request.state.is_approved = user.is_approved
                    request.state.must_change_password = user.must_change_password

        return await call_next(request)
