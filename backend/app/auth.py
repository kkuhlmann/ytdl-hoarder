"""Authentication utilities: password hashing, JWT tokens, and recovery code generation."""

import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from config import settings

# Omits 0/O/1/l/i — these codes get read off a screen and dictated over the phone.
_CODE_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


def _grouped_code(groups: int = 3, size: int = 4) -> str:
    return '-'.join(
        ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(size)) for _ in range(groups)
    )


def generate_temp_password() -> str:
    """Generate a human-transcribable temporary password (~59 bits of entropy)."""
    return _grouped_code()


def generate_recovery_code() -> str:
    """Generate a single-use admin recovery code.

    Uppercased so it reads as a code rather than a password in the file drop; entropy
    is unchanged, and the alphabet stays unambiguous either way.
    """
    return _grouped_code().upper()


def create_jwt_token(user_id: int, username: str, is_admin: bool) -> str:
    """Create a JWT token with user claims.

    The token includes user_id, username, is_admin, an issued-at, and an expiry timestamp.
    is_approved is intentionally excluded — it's checked from the DB on /me
    so that revoking approval takes effect immediately without waiting for
    token expiry.

    `iat` is what lets a password change invalidate tokens issued before it; see
    middleware/auth.py. It carries sub-second precision rather than the conventional
    whole seconds: a token minted in the same second as a password change would
    otherwise be indistinguishable from one minted just before it, and would survive
    the change. RFC 7519 NumericDate permits a non-integer value.
    """
    now = datetime.now(UTC)
    payload = {
        'user_id': user_id,
        'username': username,
        'is_admin': is_admin,
        'iat': now.timestamp(),
        'exp': now + timedelta(days=settings.auth.jwt_expiry_days),
    }
    return jwt.encode(payload, settings.auth.secret_key, algorithm=settings.auth.algorithm)


def decode_jwt_token(token: str) -> dict | None:
    """Decode and validate a JWT token.

    Returns the payload dict on success, or None if the token is invalid/expired.
    """
    try:
        return jwt.decode(token, settings.auth.secret_key, algorithms=[settings.auth.algorithm])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
