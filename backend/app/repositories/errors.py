"""Transport-agnostic repository errors, translated to HTTP in main.py."""


class NotFoundError(Exception):
    """Entity lookup failed; translated to HTTP 404."""


class InvalidStateError(Exception):
    """Operation not valid for the entity's current state; translated to HTTP 400."""
