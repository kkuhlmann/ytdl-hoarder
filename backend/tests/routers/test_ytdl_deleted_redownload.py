"""Tests for re-downloading a previously-deleted video via POST /ytdl/.

An owner re-requesting a video they soft-deleted (without overwrite) should get a 409
whose message the frontend toasts, plus a retryable FAILED download TaskRecord wired for
retry-with-overwrite. Non-owners and overwrite=True still fall through to the pipeline.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from sqlmodel import select

from database import db
from models import DownloadJob, MediaDetails, MediaType, TaskRecord, TaskStatus, TaskType

DELETED_URL = 'https://www.youtube.com/watch?v=DeLeTeD0001'


def _owner_id() -> int:
    """The authenticated fixture user owns all seeded media."""
    session = db.get_sync_session()
    try:
        return session.execute(select(MediaDetails.owner_id)).scalars().first()
    finally:
        session.close()


def _insert_deleted_media(url: str, owner_id: int, media_type: MediaType = MediaType.VIDEO) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)
    session = db.get_sync_session()
    try:
        md = MediaDetails(
            url=url,
            media_type=media_type,
            channel='Deleted Channel',
            title='Deleted Video',
            status=TaskStatus.DELETED,
            owner_id=owner_id,
            created_at=now,
        )
        session.add(md)
        session.commit()
        session.refresh(md)
        return md.id
    finally:
        session.close()


async def test_deleted_redownload_without_overwrite_creates_failed_task(
    monkeypatch, authenticated_client
):
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    owner_id = _owner_id()
    md_id = _insert_deleted_media(DELETED_URL, owner_id)

    response = authenticated_client.post(
        '/ytdl/',
        json={
            'url': DELETED_URL,
            'media_type': 'VIDEO',
            'audio_only': False,
            'download_playlist': False,
            'overwrite': False,
            'generate_transcript': False,
        },
    )

    # 409 with a message the frontend turns into a toast
    assert response.status_code == 409
    detail = response.json()['detail']
    assert 'previously deleted' in detail['message'].lower()
    assert detail['media_details_id'] == md_id
    failed_task_id = detail['task_id']

    # The pipeline was NOT submitted (blocked synchronously)
    assert mock_submit.await_count == 0

    session = db.get_sync_session()
    try:
        # A retryable FAILED download TaskRecord was created with the reason
        record = session.execute(
            select(TaskRecord).where(TaskRecord.task_id == failed_task_id)
        ).scalar_one()
        assert record.status == TaskStatus.FAILED
        assert record.task_type == TaskType.DOWNLOAD
        assert record.download_job_url == DELETED_URL
        assert record.user_id == owner_id
        assert 'previously deleted' in (record.status_message or '').lower()

        # A DownloadJob was persisted for the deleted media (retry linkage)
        jobs = (
            session.execute(select(DownloadJob).where(DownloadJob.media_details_id == md_id))
            .scalars()
            .all()
        )
        assert len(jobs) >= 1

        # download_task_record_id repointed at the new record so retry can resolve it
        md = session.execute(select(MediaDetails).where(MediaDetails.id == md_id)).scalar_one()
        assert md.download_task_record_id == record.id
    finally:
        session.close()


async def test_deleted_redownload_with_overwrite_submits_pipeline(
    monkeypatch, authenticated_client
):
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    owner_id = _owner_id()
    _insert_deleted_media(DELETED_URL, owner_id)

    response = authenticated_client.post(
        '/ytdl/',
        json={
            'url': DELETED_URL,
            'media_type': 'VIDEO',
            'audio_only': False,
            'download_playlist': False,
            'overwrite': True,
            'generate_transcript': False,
        },
    )

    assert response.status_code == 201
    assert mock_submit.await_count == 1


async def test_deleted_redownload_by_non_owner_falls_through(monkeypatch, authenticated_client):
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    # A second, different user owns the deleted media
    resp = authenticated_client.post(
        '/auth/register', json={'username': 'otheruser', 'password': 'otherpass123'}
    )
    assert resp.status_code == 201
    other_user_id = resp.json()['id']

    _insert_deleted_media(DELETED_URL, other_user_id)

    # The authenticated (first) user re-downloading someone else's deleted media
    # should NOT be blocked — it falls through to the pipeline (fresh re-download).
    response = authenticated_client.post(
        '/ytdl/',
        json={
            'url': DELETED_URL,
            'media_type': 'VIDEO',
            'audio_only': False,
            'download_playlist': False,
            'overwrite': False,
            'generate_transcript': False,
        },
    )

    assert response.status_code == 201
    assert mock_submit.await_count == 1


async def test_existing_complete_media_still_conflicts(monkeypatch, authenticated_client):
    """Regression: a non-deleted, owned media without overwrite still 409s via the original path."""
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    # Seeded media id=1 is COMPLETE/AUDIO and owned by the fixture user
    response = authenticated_client.post(
        '/ytdl/',
        json={
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'media_type': 'AUDIO',
            'audio_only': True,
            'download_playlist': False,
            'overwrite': False,
            'generate_transcript': False,
        },
    )

    assert response.status_code == 409
    assert 'overwrite' in response.json()['detail']['message'].lower()
    assert mock_submit.await_count == 0
