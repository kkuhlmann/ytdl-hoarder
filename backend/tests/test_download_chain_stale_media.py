"""Tests for _persist_download_chain_state resilience to a stale/deleted MediaDetails.

An overlapping same-URL job with overwrite=True deletes-and-recreates the
MediaDetails row while a sibling create_download_and_transcript_chains task is
still queued with the *old* media_details id baked into its job payload. When
the sibling finally runs it must not insert a download_jobs row pointing at the
now-deleted id (ForeignKeyViolation → crash → orphaned QUEUED task records).
"""

from unittest.mock import MagicMock, patch

from sqlalchemy.exc import IntegrityError

from models import MediaType, TaskStatus, TaskType
from schemas import DownloadJobDTO, MediaDetailsDTO
from tasks.media import _persist_download_chain_state

URL = 'https://www.youtube.com/watch?v=OdFrwLnnebQ'


def _make_dto(stale_id: int) -> DownloadJobDTO:
    """DTO whose payload media_details.id is the (potentially stale) id."""
    md = MediaDetailsDTO(
        id=stale_id,
        url=URL,
        media_type=MediaType.AUDIO,
        title='Move Into Light',
        channel='Alphabeta Music',
        owner_id=1,
    )
    return DownloadJobDTO(
        url=URL,
        media_type=MediaType.AUDIO,
        user_id=1,
        media_details=md,
    )


def _assign_ids(records: list) -> list[int]:
    for index, record in enumerate(records, start=101):
        record.id = index
    return [record.id for record in records]


@patch('tasks.media.dj_repo')
@patch('tasks.media.tr_repo')
@patch('tasks.media.md_repo')
def test_skips_when_media_details_deleted(mock_md_repo, mock_tr_repo, mock_dj_repo):
    """MediaDetails gone from DB (deleted by overwrite sibling) → skip, insert nothing."""
    mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = None

    dto = _make_dto(stale_id=17765)
    result = _persist_download_chain_state(
        dto, create_download_task=True, create_transcript_task=False
    )

    assert result is None
    mock_tr_repo.sync_insert_many_tasks.assert_not_called()
    mock_dj_repo.sync_add_download_job.assert_not_called()


@patch('tasks.media.dj_repo')
@patch('tasks.media.tr_repo')
@patch('tasks.media.md_repo')
def test_uses_live_media_details_id_not_stale_payload(mock_md_repo, mock_tr_repo, mock_dj_repo):
    """The download_jobs row must reference the *live* MediaDetails id, not the payload id."""
    live_md = MagicMock()
    live_md.id = 17766  # overwrite sibling recreated the row under a new id
    mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = live_md
    # Stand in for the flush that populates TaskRecord.id — the FK back-reference is
    # read off the inserted record, so a mock that leaves it None tests nothing.
    mock_tr_repo.sync_insert_many_tasks.side_effect = _assign_ids

    dto = _make_dto(stale_id=17765)
    result = _persist_download_chain_state(
        dto, create_download_task=True, create_transcript_task=False
    )

    assert result is not None
    persisted_job = mock_dj_repo.sync_add_download_job.call_args.args[0]
    assert persisted_job.media_details_id == 17766
    # FK back-reference on MediaDetails is written against the live id too
    assert mock_md_repo.sync_update_one.call_args.args[0] == 17766


@patch('tasks.media.dj_repo')
@patch('tasks.media.tr_repo')
@patch('tasks.media.md_repo')
def test_rolls_back_task_records_on_fk_violation(mock_md_repo, mock_tr_repo, mock_dj_repo):
    """Narrow TOCTOU: row deleted between re-resolve and insert → clean up task records, skip."""
    live_md = MagicMock()
    live_md.id = 17766
    mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = live_md
    mock_tr_repo.sync_insert_many_tasks.return_value = [101, 102]
    mock_dj_repo.sync_add_download_job.side_effect = IntegrityError('INSERT', {}, Exception('fk'))

    dto = _make_dto(stale_id=17765)
    result = _persist_download_chain_state(
        dto, create_download_task=True, create_transcript_task=False
    )

    assert result is None
    mock_tr_repo.sync_delete_tasks_by_ids.assert_called_once_with([101, 102])


# --- sprite row created alongside the chain ---


def _make_video_dto() -> DownloadJobDTO:
    md = MediaDetailsDTO(
        id=42,
        url=URL,
        media_type=MediaType.VIDEO,
        title='Some Video',
        channel='Some Channel',
        owner_id=1,
    )
    return DownloadJobDTO(url=URL, media_type=MediaType.VIDEO, user_id=1, media_details=md)


@patch('tasks.media.dj_repo')
@patch('tasks.media.tr_repo')
@patch('tasks.media.md_repo')
def test_video_chain_inserts_a_sprite_row(mock_md_repo, mock_tr_repo, mock_dj_repo):
    mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = MagicMock(id=42)

    _persist_download_chain_state(
        _make_video_dto(),
        create_download_task=True,
        create_transcript_task=True,
        create_sprite_task=True,
    )

    documents = mock_tr_repo.sync_insert_many_tasks.call_args[0][0]
    assert len(documents) == 3
    sprite = documents[2]
    assert sprite.task_type == TaskType.SPRITE_GENERATION
    assert sprite.status == TaskStatus.QUEUED
    assert sprite.upstream_task_ids == [documents[0].task_id]
    # Null sequence is the "not dispatched yet" marker read by recovery and by
    # the queue-position display.
    assert sprite.queue_sequence is None


@patch('tasks.media.dj_repo')
@patch('tasks.media.tr_repo')
@patch('tasks.media.md_repo')
def test_audio_chain_has_no_sprite_row(mock_md_repo, mock_tr_repo, mock_dj_repo):
    mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = MagicMock(id=42)

    _persist_download_chain_state(
        _make_dto(stale_id=42), create_download_task=True, create_transcript_task=True
    )

    documents = mock_tr_repo.sync_insert_many_tasks.call_args[0][0]
    assert len(documents) == 2
    assert all(d.task_type != TaskType.SPRITE_GENERATION for d in documents)


@patch('tasks.media.dj_repo')
@patch('tasks.media.tr_repo')
@patch('tasks.media.md_repo')
def test_cancelled_sprite_slot_released_before_insert(mock_md_repo, mock_tr_repo, mock_dj_repo):
    """The insert is all-or-nothing, so a stale CANCELLED row would drop the whole chain."""
    mock_md_repo.sync_get_media_details_by_url_and_media_type.return_value = MagicMock(id=42)
    calls = []
    mock_tr_repo.sync_release_cancelled_task_slot.side_effect = lambda *a: calls.append('release')
    mock_tr_repo.sync_insert_many_tasks.side_effect = lambda docs: (
        calls.append('insert') or [1, 2, 3]
    )

    _persist_download_chain_state(
        _make_video_dto(),
        create_download_task=True,
        create_transcript_task=True,
        create_sprite_task=True,
    )

    assert calls == ['release', 'insert']
    assert mock_tr_repo.sync_release_cancelled_task_slot.call_args[0][2] == (
        TaskType.SPRITE_GENERATION
    )
