"""Unit tests for the effective-user-id dependencies."""

from types import SimpleNamespace

from dependencies import get_admin_override, get_effective_user_id


def _request(is_admin: bool):
    return SimpleNamespace(state=SimpleNamespace(is_admin=is_admin))


def test_effective_user_id_admin_view_by_admin_is_unfiltered():
    assert get_effective_user_id(_request(True), admin_view=True, user_id=7) is None


def test_effective_user_id_admin_view_by_non_admin_stays_filtered():
    assert get_effective_user_id(_request(False), admin_view=True, user_id=7) == 7


def test_effective_user_id_default_is_own_id():
    assert get_effective_user_id(_request(True), admin_view=False, user_id=7) == 7


def test_admin_override():
    assert get_admin_override(_request(True), admin_view=True) is True
    assert get_admin_override(_request(True), admin_view=False) is False
    assert get_admin_override(_request(False), admin_view=True) is False
