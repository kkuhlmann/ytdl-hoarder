"""Regression tests for concurrent-download-chain race conditions.

Covers the follow-ups to the stale-MediaDetails fix (commit 0998187):

- download_youtube re-resolves MediaDetails by url+media_type at execution time
  instead of trusting the payload id captured at populate time
- _reuse_or_delete_existing_media never hard-deletes a row an in-flight chain
  still references
- YtPostProcessor updates by primary key instead of flushing a detached instance
- _handle_playlist_creation survives losing the playlist get-or-create race
  (backed by uq_playlists_source_url)
- sync_upsert_media_details survives losing the insert race on
  uq_media_details_url_type and never clobbers a live status with the NONE default
- _record_not_ready_task survives losing the placeholder insert race
  (backed by ix_task_records_not_ready_unique)
- create_download_and_transcript_chains stands down when a live task already
  owns the URL
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import db
from models import MediaDetails, MediaType, TaskRecord, TaskStatus, TaskType
from repositories import media_details as md_repo
from repositories import playlists as playlist_repo
from repositories import task_records as tr_repo
from schemas import DownloadJobDTO, MediaDetailsDTO
from serializers import serialize_download_job
from tasks.downloads import _resolve_live_media_details
from tasks.media import (
    _handle_playlist_creation,
    _record_not_ready_task,
    _reuse_or_delete_existing_media,
)
from tasks.media import (
    create_download_and_transcript_chains_impl as create_download_and_transcript_chains,
)
from ytdlp.options import YtPostProcessor

URL = 'https://www.youtube.com/watch?v=raceCond01'


def _make_dto(**overrides) -> DownloadJobDTO:
    payload_md = MediaDetailsDTO(id=10, url=URL, media_type=MediaType.AUDIO, title='Old Title')
    defaults = {
        'url': URL,
        'media_type': MediaType.AUDIO,
        'user_id': 1,
        'media_details': payload_md,
    }
    defaults.update(overrides)
    return DownloadJobDTO(**defaults)


def _make_orm(**overrides) -> MediaDetails:
    from datetime import datetime

    defaults = {
        'id': 10,
        'url': URL,
        'media_type': MediaType.AUDIO,
        'title': 'Old Title',
        'channel': 'Chan',
        'release_timestamp': datetime(2026, 1, 1),
        'owner_id': 1,
    }
    defaults.update(overrides)
    return MediaDetails(**defaults)


# --- download_youtube re-resolve (stale payload id) ---


class TestResolveLiveMediaDetails:
    @patch('tasks.downloads.md_repo')
    def test_returns_none_when_row_deleted(self, mock_md_repo):
        """Row gone entirely → superseded, caller must skip the download."""
        mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = None

        assert _resolve_live_media_details(_make_dto()) is None

    @patch('tasks.downloads.md_repo')
    def test_swaps_in_live_row_when_replaced(self, mock_md_repo):
        """Row deleted+recreated under a new id → DTO rebuilt around the live row."""
        live = _make_orm(id=99, title='New Title')
        mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = live

        result = _resolve_live_media_details(_make_dto())

        assert result is not None
        assert result.media_details.id == 99
        assert result.existing_media_details_id == 99
        assert result.media_details.title == 'New Title'

    @patch('tasks.downloads.md_repo')
    def test_unchanged_when_id_matches(self, mock_md_repo):
        """Live row still has the payload id → DTO passes through untouched."""
        mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = _make_orm(id=10)

        dto = _make_dto()
        assert _resolve_live_media_details(dto) is dto

    @patch('tasks.downloads.md_repo')
    def test_unchanged_without_persisted_media_details(self, mock_md_repo):
        """No persisted media_details in the payload → nothing to re-resolve."""
        dto = _make_dto(media_details=None)

        assert _resolve_live_media_details(dto) is dto
        mock_md_repo.sync_get_media_details_by_url_and_media_type.assert_not_called()


# --- _reuse_or_delete_existing_media in-flight guard ---


class TestInFlightDeleteGuard:
    @patch('tasks.media.tr_repo')
    @patch('tasks.media.md_repo')
    def test_overwrite_skips_delete_when_chain_in_flight(self, mock_md_repo, mock_tr_repo):
        """Overwrite must not hard-delete a row a queued/running chain references."""
        orm_obj = _make_orm()
        mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = orm_obj
        mock_tr_repo.sync_find_active_by_url_and_type.return_value = MagicMock()  # in flight

        result = _reuse_or_delete_existing_media(_make_dto(overwrite=True, media_details=None))

        mock_md_repo.sync_delete_by_url_and_media_type.assert_not_called()
        # The surviving row is reused instead
        assert result.existing_media_details_id == orm_obj.id

    @patch('tasks.media.tr_repo')
    @patch('tasks.media.md_repo')
    def test_skipped_recreate_skips_delete_when_chain_in_flight(self, mock_md_repo, mock_tr_repo):
        """SKIPPED-recreate must not hard-delete a row a sibling chain is re-downloading."""
        orm_obj = _make_orm(status=TaskStatus.SKIPPED)
        mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = orm_obj
        mock_tr_repo.sync_find_active_by_url_and_type.return_value = MagicMock()  # in flight

        _reuse_or_delete_existing_media(_make_dto(media_details=None))

        mock_md_repo.sync_delete_by_url_and_media_type.assert_not_called()


# --- YtPostProcessor updates by primary key ---


class TestYtPostProcessor:
    @patch('ytdlp.options.md_repo')
    def test_updates_by_id(self, mock_md_repo):
        pp = YtPostProcessor(42)

        pp.run({'filepath': '/nonexistent/file.m4a'})

        # getsize fails on the nonexistent path → only file_path is written
        mock_md_repo.sync_update_by_id.assert_called_once_with(
            42, file_path='/nonexistent/file.m4a'
        )

    @patch('ytdlp.options.md_repo')
    def test_missing_row_does_not_raise(self, mock_md_repo):
        """Row replaced mid-download → warn and continue, never StaleDataError."""
        mock_md_repo.sync_update_by_id.return_value = None

        result = YtPostProcessor(42).run({'filepath': '/nonexistent/file.m4a'})

        assert result == ([], {'filepath': '/nonexistent/file.m4a'})


# --- _handle_playlist_creation get-or-create race ---


class TestPlaylistCreationRace:
    @patch('repositories.playlists.sync_add_media_to_playlist')
    @patch('repositories.playlists.sync_get_next_position', return_value=1)
    @patch('repositories.playlists.sync_create_playlist')
    @patch('repositories.playlists.sync_get_playlist_by_source_url')
    def test_lost_create_race_reuses_winner(self, mock_get, mock_create, mock_pos, mock_add):
        """Losing the insert on uq_playlists_source_url → re-fetch and use the winner."""
        winner = MagicMock(id=7, name='My Playlist')
        mock_get.side_effect = [None, winner]  # miss before create, hit after losing race
        mock_create.side_effect = IntegrityError('INSERT', {}, Exception('unique'))

        dto = _make_dto(
            playlist_name='My Playlist',
            source_playlist_url='https://www.youtube.com/playlist?list=PLrace',
            existing_media_details_id=10,
        )
        _handle_playlist_creation(dto)

        assert mock_add.call_args.kwargs['playlist_id'] == 7
        assert mock_add.call_args.kwargs['media_details_id'] == 10

    @patch('repositories.playlists.sync_add_media_to_playlist')
    @patch('repositories.playlists.sync_get_next_position', return_value=1)
    @patch('repositories.playlists.sync_get_playlist_by_source_url')
    def test_lost_add_race_is_swallowed(self, mock_get, mock_pos, mock_add):
        """Concurrent add of the same media (uq_playlist_media) must not kill populate."""
        mock_get.return_value = MagicMock(id=7, name='My Playlist')
        mock_add.side_effect = IntegrityError('INSERT', {}, Exception('unique'))

        dto = _make_dto(
            playlist_name='My Playlist',
            source_playlist_url='https://www.youtube.com/playlist?list=PLrace',
            existing_media_details_id=10,
        )
        _handle_playlist_creation(dto)  # must not raise


# --- _record_not_ready_task placeholder insert race ---


class TestNotReadyPlaceholderRace:
    @patch('tasks.media.publish_status_change')
    @patch('tasks.media.tr_repo')
    def test_lost_insert_race_refreshes_winner(self, mock_tr_repo, mock_publish):
        """Losing the insert on ix_task_records_not_ready_unique → update winner's row."""
        winner = MagicMock(task_id='winner-not-ready')
        mock_tr_repo.sync_find_active_by_url_and_type.return_value = None
        # No placeholder before our insert; the winner's row exists after we lose
        mock_tr_repo.sync_find_latest_not_ready_task.side_effect = [None, winner]
        mock_tr_repo.sync_insert_task.side_effect = IntegrityError(
            'INSERT', {}, Exception('unique')
        )

        _record_not_ready_task(_make_dto(), {'title': 'Premiere'}, 'is an upcoming premiere')

        assert mock_tr_repo.sync_update_one.call_args.args[0] == 'winner-not-ready'
        assert mock_publish.call_args.args[0] == 'winner-not-ready'


# Persisted-but-never-dispatched QUEUED records are handled by startup
# recovery (tests/orchestrator/test_recovery.py), which re-enqueues them from
# the DB. A live duplicate is always a plain skip:


class TestDuplicateActiveTask:
    def _job(self) -> dict:
        return serialize_download_job(
            DownloadJobDTO(url=URL, media_type=MediaType.AUDIO, generate_transcript=False)
        )

    @patch('tasks.media.tr_repo')
    def test_existing_queued_record_skips_dispatch(self, mock_tr_repo):
        live = MagicMock(status=TaskStatus.QUEUED, queue_sequence=1234, task_id='dl-live-1')
        mock_tr_repo.sync_find_one.return_value = live

        result = create_download_and_transcript_chains(self._job())

        assert result == {'download_queued': False, 'transcript_queued': False}
        mock_tr_repo.dispatch_download_chain.assert_not_called()

    @patch('tasks.media.tr_repo')
    def test_in_progress_record_skips_dispatch(self, mock_tr_repo):
        running = MagicMock(status=TaskStatus.IN_PROGRESS, queue_sequence=None)
        mock_tr_repo.sync_find_one.return_value = running

        result = create_download_and_transcript_chains(self._job())

        assert result == {'download_queued': False, 'transcript_queued': False}
        mock_tr_repo.dispatch_download_chain.assert_not_called()


# --- DB-backed tests: constraints + upsert semantics ---


def test_upsert_insert_race_falls_back_to_update(test_database, monkeypatch):
    """Losing the insert race on uq_media_details_url_type updates the winner's row.

    Simulated deterministically: the first flush that tries to INSERT our row first
    commits a competing row for the same (url, media_type) through a separate
    session, so the flush hits the unique index exactly like a concurrent chain
    would. The upsert must fall back to updating the winner's row.
    """
    url = f'https://www.youtube.com/watch?v={uuid.uuid4().hex[:11]}'
    original_flush = Session.flush
    state = {'raced': False}

    def racing_flush(self, *args, **kwargs):
        if not state['raced'] and self.new:
            state['raced'] = True
            with db.sync_session() as s2:
                s2.add(
                    MediaDetails(
                        url=url,
                        media_type=MediaType.AUDIO,
                        title='winner',
                        status=TaskStatus.COMPLETE,
                    )
                )
        return original_flush(self, *args, **kwargs)

    monkeypatch.setattr(Session, 'flush', racing_flush)

    result = md_repo.sync_upsert_media_details(
        MediaDetails(url=url, media_type=MediaType.AUDIO, title='loser')
    )

    winner = md_repo.sync_get_media_details_by_url_and_media_type(url, MediaType.AUDIO.value)
    assert result.id == winner.id
    assert winner.title == 'loser'  # metadata from the losing upsert was applied
    assert winner.status == TaskStatus.COMPLETE  # NONE default did not clobber it


def test_upsert_none_status_does_not_clobber_existing(test_database):
    """The TaskStatus.NONE model default means 'unset' — it must never overwrite."""
    url = f'https://www.youtube.com/watch?v={uuid.uuid4().hex[:11]}'
    md_repo.sync_upsert_media_details(
        MediaDetails(url=url, media_type=MediaType.AUDIO, title='a', status=TaskStatus.COMPLETE)
    )

    result = md_repo.sync_upsert_media_details(
        MediaDetails(url=url, media_type=MediaType.AUDIO, title='b')
    )

    assert result.title == 'b'
    assert result.status == TaskStatus.COMPLETE

    # An explicit status still updates
    result = md_repo.sync_upsert_media_details(
        MediaDetails(url=url, media_type=MediaType.AUDIO, status=TaskStatus.SKIPPED)
    )
    assert result.status == TaskStatus.SKIPPED


def test_playlists_source_url_unique_index(test_database):
    """uq_playlists_source_url backs the get-or-create in _handle_playlist_creation."""
    source_url = 'https://www.youtube.com/playlist?list=PLuniq'
    playlist_repo.sync_create_playlist(name='One', source_url=source_url)

    with pytest.raises(IntegrityError):
        playlist_repo.sync_create_playlist(name='Two', source_url=source_url)

    # NULL source_url playlists (user-created) are unconstrained
    playlist_repo.sync_create_playlist(name='Manual 1')
    playlist_repo.sync_create_playlist(name='Manual 2')


def test_not_ready_placeholder_unique_index(test_database):
    """ix_task_records_not_ready_unique backs the placeholder upsert."""

    def _placeholder() -> TaskRecord:
        return TaskRecord(
            task_id=str(uuid.uuid4()),
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.NOT_READY,
            media_type=MediaType.AUDIO,
            download_job_url=URL,
        )

    tr_repo.sync_insert_task(_placeholder())
    with pytest.raises(IntegrityError):
        tr_repo.sync_insert_task(_placeholder())

    # Soft-deleted placeholders vacate the index slot
    assert tr_repo.sync_soft_delete_not_ready_tasks(URL, MediaType.AUDIO) == 1
    tr_repo.sync_insert_task(_placeholder())
