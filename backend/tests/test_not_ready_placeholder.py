"""Tests for the visible NOT_READY placeholder task records.

Covers the not-ready status message builder and the Path A placeholder
upsert created when populate_media_details defers an unreleased video.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from models import MediaType, TaskRecord, TaskStatus, TaskType
from repositories import task_records
from schemas import DownloadJobDTO
from tasks.media import _persist_download_chain_state, _record_not_ready_task
from ytdlp.info import build_not_ready_message


def _make_dto(**overrides) -> DownloadJobDTO:
    defaults = {
        'url': 'https://www.youtube.com/watch?v=premiere1',
        'media_type': MediaType.AUDIO,
        'user_id': None,
    }
    defaults.update(overrides)
    return DownloadJobDTO(**defaults)


def _make_info(**overrides) -> dict:
    future_ts = int((datetime.now() + timedelta(days=1)).timestamp())
    defaults = {
        'title': 'Premiere Video',
        'channel': 'Test Channel',
        'live_status': 'is_upcoming',
        'release_timestamp': future_ts,
    }
    defaults.update(overrides)
    return defaults


class TestBuildNotReadyMessage:
    """Tests for build_not_ready_message."""

    def test_starts_with_reason(self):
        msg = build_not_ready_message('Video is currently live', None, False)
        assert msg.startswith('Video is currently live.')

    def test_subscription_suffix(self):
        msg = build_not_ready_message('Video is an upcoming premiere', None, True)
        assert msg.endswith('Will retry when the subscription checks again.')

    def test_manual_suffix(self):
        msg = build_not_ready_message('Video is an upcoming premiere', None, False)
        assert msg.endswith('Try again when the video is available.')

    def test_future_timestamp_adds_premiere_time(self):
        future = datetime.now() + timedelta(days=2)
        msg = build_not_ready_message('Video is an upcoming premiere', future, True)
        assert f'Premieres {future:%Y-%m-%d %H:%M}.' in msg

    def test_past_timestamp_omits_premiere_time(self):
        past = datetime.now() - timedelta(days=2)
        msg = build_not_ready_message('Video is still processing after live stream', past, True)
        assert 'Premieres' not in msg

    def test_no_timestamp_omits_premiere_time(self):
        msg = build_not_ready_message('Video is currently live', None, True)
        assert 'Premieres' not in msg

    def test_aware_future_timestamp_handled(self):
        """Path B passes tz-aware timestamps (from MediaDetailsDTO) — must not raise."""
        future = datetime.now(UTC) + timedelta(days=2)
        msg = build_not_ready_message('Video is an upcoming premiere', future, False)
        assert 'Premieres' in msg

    def test_aware_past_timestamp_handled(self):
        past = datetime.now(UTC) - timedelta(days=2)
        msg = build_not_ready_message('Video is currently live', past, False)
        assert 'Premieres' not in msg


class TestRecordNotReadyTask:
    """Unit tests for the Path A placeholder upsert."""

    @patch('tasks.media.publish_status_change')
    @patch('tasks.media.tr_repo')
    def test_inserts_placeholder_when_absent(self, mock_tr_repo, mock_publish):
        mock_tr_repo.sync_find_active_by_url_and_type.return_value = None
        mock_tr_repo.sync_find_latest_not_ready_task.return_value = None

        dto = _make_dto(user_id=5, subscription_id=7)
        _record_not_ready_task(dto, _make_info(), 'Video is an upcoming premiere')

        mock_tr_repo.sync_insert_task.assert_called_once()
        record = mock_tr_repo.sync_insert_task.call_args.args[0]
        assert record.status == TaskStatus.NOT_READY
        assert record.task_type == TaskType.DOWNLOAD
        assert record.download_job_url == dto.url
        assert record.media_type == MediaType.AUDIO
        assert record.title == 'Premiere Video'
        assert record.channel == 'Test Channel'
        assert record.release_timestamp is not None
        assert record.user_id == 5
        assert record.status_message.startswith('Video is an upcoming premiere.')
        assert record.status_message.endswith('Will retry when the subscription checks again.')
        mock_tr_repo.sync_update_one.assert_not_called()
        mock_publish.assert_called_once()
        assert mock_publish.call_args.args[0] == record.task_id
        assert mock_publish.call_args.args[1] == TaskStatus.NOT_READY.value

    @patch('tasks.media.publish_status_change')
    @patch('tasks.media.tr_repo')
    def test_updates_existing_placeholder(self, mock_tr_repo, mock_publish):
        existing = MagicMock()
        existing.task_id = 'existing-not-ready'
        mock_tr_repo.sync_find_active_by_url_and_type.return_value = None
        mock_tr_repo.sync_find_latest_not_ready_task.return_value = existing

        dto = _make_dto()
        _record_not_ready_task(dto, _make_info(), 'Video is currently live')

        mock_tr_repo.sync_insert_task.assert_not_called()
        mock_tr_repo.sync_update_one.assert_called_once()
        task_id, fields = mock_tr_repo.sync_update_one.call_args.args
        assert task_id == 'existing-not-ready'
        assert fields['status'] == TaskStatus.NOT_READY
        assert fields['status_message'].endswith('Try again when the video is available.')
        mock_publish.assert_called_once()
        assert mock_publish.call_args.args[0] == 'existing-not-ready'

    @patch('tasks.media.publish_status_change')
    @patch('tasks.media.tr_repo')
    def test_skips_when_active_task_exists(self, mock_tr_repo, mock_publish):
        mock_tr_repo.sync_find_active_by_url_and_type.return_value = MagicMock()

        _record_not_ready_task(_make_dto(), _make_info(), 'Video is currently live')

        mock_tr_repo.sync_insert_task.assert_not_called()
        mock_tr_repo.sync_update_one.assert_not_called()
        mock_publish.assert_not_called()


class TestRecordNotReadyTaskIntegration:
    """Integration tests against the real database."""

    @patch('tasks.media.publish_status_change')
    def test_upsert_creates_single_row(self, mock_publish, test_database):
        url = 'https://www.youtube.com/watch?v=upsert1'
        dto = _make_dto(url=url)
        info = _make_info()

        _record_not_ready_task(dto, info, 'Video is an upcoming premiere')
        _record_not_ready_task(dto, info, 'Video is an upcoming premiere')

        # sync_find_one raises MultipleResultsFound if the upsert duplicated rows
        row = task_records.sync_find_one({'download_job_url': url})
        assert row is not None
        assert row.status == TaskStatus.NOT_READY
        assert row.deleted_at is None


class TestPersistChainClearsPlaceholder:
    """When the video airs, the placeholder is soft-deleted and replaced by a real chain."""

    def test_placeholder_soft_deleted_on_release(self, test_database):
        url = 'https://www.youtube.com/watch?v=release1'
        task_records.sync_insert_task(
            TaskRecord(
                task_id='placeholder-release1',
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.NOT_READY,
                download_job_url=url,
                media_type=MediaType.AUDIO,
            )
        )

        dto = _make_dto(url=url)
        result = _persist_download_chain_state(dto, True, False)
        assert result is not None
        download_task_id, _ = result

        old = task_records.sync_get_task_by_task_id('placeholder-release1')
        assert old.deleted_at is not None

        new = task_records.sync_get_task_by_task_id(download_task_id)
        assert new is not None
        assert new.status == TaskStatus.QUEUED
        assert new.deleted_at is None
