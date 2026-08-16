"""Tests for _handle_video_not_ready (download-time safety net).

When the download task finds a video isn't released yet, it must not leave an
incomplete media_details row behind: delete it if nothing was downloaded, or
mark it NOT_READY if a file already exists. The task record keeps NOT_READY
status with a user-facing message and an SSE event so the UI updates live.
"""

from unittest.mock import MagicMock, patch

from models import MediaType, TaskStatus
from orchestrator import DownloadHooks
from schemas import DownloadJobDTO, MediaDetailsDTO
from tasks.downloads import _handle_video_not_ready


def _make_dto_with_media(media_id: int = 42, **overrides) -> DownloadJobDTO:
    md = MediaDetailsDTO(
        id=media_id,
        url='https://www.youtube.com/watch?v=abc123',
        media_type=MediaType.AUDIO,
        title='Premiere',
        owner_id=1,
    )
    defaults = {
        'url': 'https://www.youtube.com/watch?v=abc123',
        'media_type': MediaType.AUDIO,
        'user_id': 1,
        'media_details': md,
    }
    defaults.update(overrides)
    return DownloadJobDTO(**defaults)


@patch('tasks.downloads.publish_status_change')
@patch('tasks.downloads.tr_repo')
@patch('tasks.downloads.md_repo')
def test_deletes_row_when_no_file(mock_md_repo, mock_tr_repo, mock_publish):
    """A not-ready video with no downloaded file should have its row deleted."""
    md_orm = MagicMock()
    md_orm.file_path = None
    mock_md_repo.sync_get_media_details_by_id.return_value = md_orm

    dto = _make_dto_with_media()
    result = _handle_video_not_ready('task-1', dto, 'Video is an upcoming premiere')

    mock_md_repo.sync_delete_by_url_and_media_type.assert_called_once_with(md_orm)
    mock_md_repo.sync_update_one.assert_not_called()
    mock_tr_repo.sync_mark_downstream_as_not_ready.assert_called_once_with('task-1')
    assert result['status'] == TaskStatus.NOT_READY.value

    expected_msg = 'Video is an upcoming premiere. Try again when the video is available.'
    mock_tr_repo.sync_update_one.assert_called_once_with(
        'task-1',
        {'status': TaskStatus.NOT_READY, 'status_message': expected_msg},
    )
    mock_publish.assert_called_once_with(
        'task-1', TaskStatus.NOT_READY.value, expected_msg, user_id=1
    )


@patch('tasks.downloads.publish_status_change')
@patch('tasks.downloads.tr_repo')
@patch('tasks.downloads.md_repo')
def test_keeps_row_when_file_exists(mock_md_repo, mock_tr_repo, mock_publish):
    """A row that already has a file should be marked NOT_READY, not deleted."""
    md_orm = MagicMock()
    md_orm.file_path = '/mnt/audio/test.mp3'
    mock_md_repo.sync_get_media_details_by_id.return_value = md_orm

    dto = _make_dto_with_media()
    result = _handle_video_not_ready('task-1', dto, 'Video is currently live')

    mock_md_repo.sync_delete_by_url_and_media_type.assert_not_called()
    mock_md_repo.sync_update_one.assert_called_once_with(42, {'status': TaskStatus.NOT_READY})
    assert result['status'] == TaskStatus.NOT_READY.value


@patch('tasks.downloads.publish_status_change')
@patch('tasks.downloads.tr_repo')
@patch('tasks.downloads.md_repo')
def test_subscription_job_gets_retry_message(mock_md_repo, mock_tr_repo, mock_publish):
    """Subscription-linked jobs note that the subscription will retry automatically."""
    mock_md_repo.sync_get_media_details_by_id.return_value = None

    dto = _make_dto_with_media(subscription_id=3)
    _handle_video_not_ready('task-1', dto, 'Video is still processing after live stream')

    _, fields = mock_tr_repo.sync_update_one.call_args.args
    assert fields['status_message'] == (
        'Video is still processing after live stream. '
        'Will retry when the subscription checks again.'
    )


@patch('orchestrator.hooks.publish_status_change')
@patch('orchestrator.hooks.md_repo')
@patch('orchestrator.hooks.tr_repo')
def test_on_success_preserves_not_ready(mock_tr_repo, mock_md_repo, mock_publish):
    """on_success must not clobber the NOT_READY status set by _handle_video_not_ready."""
    task = DownloadHooks()
    retval = {'status': TaskStatus.NOT_READY.value}

    task.on_success(retval, 'task-1', [{'user_id': 1}], {})

    mock_tr_repo.sync_update_one.assert_not_called()
    mock_md_repo.sync_update_one.assert_not_called()
    mock_publish.assert_not_called()


class TestCancelWritesTerminalMediaStatus:
    """Cancel was the only lifecycle path that left MediaDetails.status untouched.

    before_start/on_success/on_failure all write it, so a cancelled row kept
    populate's NONE — which is absent from _FILTER_SKIP_STATUSES, so every later
    subscription tick re-included the URL and spawned a populate job that could never
    produce a download (the CANCELLED TaskRecord blocks task creation).
    """

    def _job(self):
        return {
            'url': 'https://www.youtube.com/watch?v=cancelled1',
            'media_type': 'VIDEO',
            'title': 'Cancelled Video',
            'media_details': {'id': 7, 'url': 'https://www.youtube.com/watch?v=cancelled1'},
        }

    @patch('orchestrator.hooks.cleanup_task_files', return_value=0)
    @patch('orchestrator.hooks.md_repo')
    def test_on_cancel_marks_media_cancelled(self, mock_md_repo, _cleanup):
        DownloadHooks().on_cancel('task-1', (self._job(),))

        mock_md_repo.sync_mark_download_cancelled.assert_called_once_with(
            'https://www.youtube.com/watch?v=cancelled1', 'VIDEO'
        )

    @patch('orchestrator.hooks.cleanup_task_files', return_value=0)
    @patch('orchestrator.hooks.md_repo')
    def test_on_cancel_without_url_is_a_noop(self, mock_md_repo, _cleanup):
        DownloadHooks().on_cancel('task-1', ({},))

        mock_md_repo.sync_mark_download_cancelled.assert_not_called()
