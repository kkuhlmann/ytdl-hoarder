"""Tests for the storage-quota check in the download task.

A user at or over their storage limit must have downloads skipped (terminal
SKIPPED status, no retry loop). Unlimited users (storage_limit_bytes=None)
and jobs carrying no owner (user_id=None) are unaffected.
"""

from unittest.mock import MagicMock, patch

import pytest

from models import MediaType, TaskStatus
from orchestrator import JobContext, SkipJob
from schemas import DownloadJobDTO, MediaDetailsDTO
from tasks.downloads import _check_storage_quota, _handle_quota_exceeded


def _make_dto(user_id: int | None = 1, media_id: int = 42) -> DownloadJobDTO:
    md = MediaDetailsDTO(
        id=media_id,
        url='https://www.youtube.com/watch?v=abc123',
        media_type=MediaType.AUDIO,
        title='Video',
        owner_id=user_id,
    )
    return DownloadJobDTO(
        url='https://www.youtube.com/watch?v=abc123',
        media_type=MediaType.AUDIO,
        user_id=user_id,
        media_details=md,
    )


@patch('tasks.downloads.user_repo')
def test_over_quota_returns_message(mock_user_repo):
    user = MagicMock()
    user.storage_limit_bytes = 1_000_000_000
    mock_user_repo.sync_get_user_by_id.return_value = user
    mock_user_repo.sync_get_user_storage_usage.return_value = 1_500_000_000

    message = _check_storage_quota(_make_dto())

    assert message is not None
    assert 'Storage limit reached' in message
    assert '1.5 GB' in message and '1.0 GB' in message


@patch('tasks.downloads.user_repo')
def test_under_quota_returns_none(mock_user_repo):
    user = MagicMock()
    user.storage_limit_bytes = 1_000_000_000
    mock_user_repo.sync_get_user_by_id.return_value = user
    mock_user_repo.sync_get_user_storage_usage.return_value = 500

    assert _check_storage_quota(_make_dto()) is None


@patch('tasks.downloads.user_repo')
def test_unlimited_user_returns_none(mock_user_repo):
    user = MagicMock()
    user.storage_limit_bytes = None
    mock_user_repo.sync_get_user_by_id.return_value = user

    assert _check_storage_quota(_make_dto()) is None
    mock_user_repo.sync_get_user_storage_usage.assert_not_called()


@patch('tasks.downloads.user_repo')
def test_job_without_user_id_returns_none(mock_user_repo):
    assert _check_storage_quota(_make_dto(user_id=None)) is None
    mock_user_repo.sync_get_user_by_id.assert_not_called()


@patch('tasks.downloads.user_repo')
def test_missing_user_returns_none(mock_user_repo):
    mock_user_repo.sync_get_user_by_id.return_value = None

    assert _check_storage_quota(_make_dto()) is None


@patch('tasks.downloads.publish_status_change')
@patch('tasks.downloads.tr_repo')
@patch('tasks.downloads.md_repo')
def test_handle_quota_exceeded_marks_skipped(mock_md_repo, mock_tr_repo, mock_publish):
    ctx = JobContext('task-1')
    dto = _make_dto()
    message = 'Storage limit reached (1.5 GB of 1.0 GB used)'

    with pytest.raises(SkipJob):
        _handle_quota_exceeded(ctx, 'task-1', dto, message)

    mock_tr_repo.sync_update_one.assert_called_once_with(
        'task-1',
        {'status': TaskStatus.SKIPPED, 'status_message': message},
    )
    mock_md_repo.sync_update_one.assert_called_once_with(42, {'status': TaskStatus.SKIPPED})
    mock_tr_repo.sync_mark_downstream_as_skipped.assert_called_once_with('task-1')
    mock_publish.assert_called_once_with('task-1', TaskStatus.SKIPPED.value, message, user_id=1)
    assert ctx.skip_downstream is True
