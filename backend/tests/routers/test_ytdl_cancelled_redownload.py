"""Tests for resubmitting a URL whose download was cancelled, via POST /ytdl/.

A cancel deliberately holds the URL's slot so the next subscription tick can't resurrect
work the user dismissed. Deleting the task record is the user's way of taking that back:
once the row is gone it must be as though the download was never queued.
"""

from unittest.mock import AsyncMock

from sqlmodel import select

from database import db
from models import MediaDetails, MediaType, TaskRecord, TaskStatus, TaskType

CANCELLED_URL = 'https://www.youtube.com/watch?v=CaNcElLeD01'


def _owner_id() -> int:
    session = db.get_sync_session()
    try:
        return session.execute(select(MediaDetails.owner_id)).scalars().first()
    finally:
        session.close()


def _seed_cancelled_download(owner_id: int) -> int:
    """The state a cancelled download leaves behind: a CANCELLED task record holding the
    URL's slot, plus the CANCELLED media stub mark_download_cancelled writes."""
    session = db.get_sync_session()
    try:
        record = TaskRecord(
            task_id='cancelled-download-task',
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.CANCELLED,
            status_message='Cancelled by user',
            title='Cancelled Video',
            download_job_url=CANCELLED_URL,
            media_type=MediaType.VIDEO,
            user_id=owner_id,
        )
        md = MediaDetails(
            url=CANCELLED_URL,
            media_type=MediaType.VIDEO,
            channel='Cancel Channel',
            title='Cancelled Video',
            status=TaskStatus.CANCELLED,
            owner_id=owner_id,
        )
        session.add(record)
        session.add(md)
        session.commit()
        session.refresh(record)
        return record.id
    finally:
        session.close()


def _submit(client):
    return client.post(
        '/ytdl/',
        json={
            'url': CANCELLED_URL,
            'media_type': 'VIDEO',
            'audio_only': False,
            'download_playlist': False,
            'overwrite': False,
            'generate_transcript': False,
        },
    )


async def test_resubmit_after_deleting_the_cancelled_task_starts_a_fresh_download(
    monkeypatch, authenticated_client
):
    """The reported bug: the delete left the row holding the URL, so the resubmit 409'd
    telling the user to retry or delete a task that was already gone."""
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    record_id = _seed_cancelled_download(_owner_id())

    delete = authenticated_client.request(
        method='DELETE', url='/tasks/bulk', json={'record_ids': [record_id]}
    )
    assert delete.status_code == 200
    assert delete.json()['deleted_count'] == 1

    response = _submit(authenticated_client)

    assert response.status_code == 201, response.text
    assert mock_submit.await_count == 1
    # The new RESOLVING placeholder could only be inserted if the deleted row released
    # its ix_task_records_active_unique slot.
    assert response.json()['task_id'] is not None


async def test_resubmit_while_the_cancelled_task_remains_is_still_blocked(
    monkeypatch, authenticated_client
):
    """The other half of the contract: an undeleted cancel keeps holding the URL, for
    whoever asks next — otherwise the next tick redownloads what the user dismissed."""
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    _seed_cancelled_download(_owner_id())

    response = _submit(authenticated_client)

    assert response.status_code == 409
    detail = response.json()['detail']
    assert 'still holds its place' in detail['message']
    assert detail['task_id'] == 'cancelled-download-task'
    assert mock_submit.await_count == 0
