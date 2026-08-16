"""Tests for the RESOLVING download placeholder, at both layers.

`POST /ytdl/` writes the row before yt-dlp runs, because the chain's TaskRecords are
only created at the end of populate and the tasks table would otherwise show nothing
for the seconds-to-minutes the metadata fetch takes. The row must be durable
(pending_payload, for startup recovery) and must reach the pipeline as
placeholder_task_id.

The chain then has to end that row in exactly one of three states: adopted as the
QUEUED download row (keeping its task_id, so the row the user has been watching never
jumps), retired to a terminal status with a readable reason, or left CANCELLED by the
user — which the chain has to honour, since the placeholder task_id is deliberately
never a JobSpec.task_id and orch.cancel therefore has nothing to dequeue.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from database import db
from models import MediaDetails, MediaType, TaskRecord, TaskStatus, TaskType
from repositories import task_records as tr_repo
from schemas import DownloadJobDTO, MediaDetailsDTO
from serializers import serialize_download_job
from tasks.media import (
    _persist_download_chain_state,
    create_download_and_transcript_chains_impl,
    guard_resolving_placeholders,
)

# =========================================================== chain level (tasks.media)


def _seed_placeholder(url: str, payload: dict | None = None) -> str:
    task_id = str(uuid.uuid4())
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.RESOLVING,
                status_message='Fetching video metadata...',
                title=url,
                media_type=MediaType.VIDEO,
                download_job_url=url,
                pending_payload=payload,
            )
        )
        session.commit()
    finally:
        session.close()
    return task_id


def _seed_media(url: str) -> int:
    session = db.get_sync_session()
    try:
        md = MediaDetails(
            url=url,
            media_type=MediaType.VIDEO,
            channel='Placeholder Channel',
            title='Placeholder Video',
            owner_id=None,
        )
        session.add(md)
        session.commit()
        session.refresh(md)
        return md.id
    finally:
        session.close()


def _reload(task_id: str) -> TaskRecord:
    session = db.get_sync_session()
    try:
        return (
            session.execute(select(TaskRecord).where(TaskRecord.task_id == task_id)).scalars().one()
        )
    finally:
        session.close()


def _download_rows(url: str) -> list[TaskRecord]:
    session = db.get_sync_session()
    try:
        return list(
            session.execute(
                select(TaskRecord).where(
                    TaskRecord.download_job_url == url,
                    TaskRecord.task_type == TaskType.DOWNLOAD,
                )
            )
            .scalars()
            .all()
        )
    finally:
        session.close()


def _dto(url: str, placeholder_task_id: str, media_id: int) -> DownloadJobDTO:
    return DownloadJobDTO(
        url=url,
        media_type=MediaType.VIDEO,
        placeholder_task_id=placeholder_task_id,
        media_details=MediaDetailsDTO(
            id=media_id,
            url=url,
            media_type=MediaType.VIDEO,
            title='Placeholder Video',
            channel='Placeholder Channel',
        ),
    )


async def test_chain_adopts_placeholder_in_place(test_database):
    url = 'https://www.youtube.com/watch?v=AdOpT000001'
    task_id = _seed_placeholder(url)
    media_id = _seed_media(url)

    result = _persist_download_chain_state(
        _dto(url, task_id, media_id), create_download_task=True, create_transcript_task=False
    )

    assert result == (task_id, None)
    rows = _download_rows(url)
    assert len(rows) == 1, 'the placeholder becomes the download row, it is not duplicated'
    assert rows[0].status == TaskStatus.QUEUED
    assert rows[0].title == 'Placeholder Video'
    assert rows[0].channel == 'Placeholder Channel'
    assert rows[0].pending_payload is None, 'payload is only needed while unresolved'


async def test_cancelled_placeholder_stands_the_chain_down(test_database):
    url = 'https://www.youtube.com/watch?v=AdOpT000002'
    task_id = _seed_placeholder(url)
    media_id = _seed_media(url)
    tr_repo.sync_update_one(task_id, {'status': TaskStatus.CANCELLED})

    result = _persist_download_chain_state(
        _dto(url, task_id, media_id), create_download_task=True, create_transcript_task=False
    )

    assert result is None
    rows = _download_rows(url)
    assert len(rows) == 1
    assert rows[0].status == TaskStatus.CANCELLED, 'a cancel during the fetch must stick'


async def test_deleted_placeholder_falls_back_to_a_fresh_row(test_database):
    """Deleting the *record* is not cancelling the *work* — the download still happens."""
    url = 'https://www.youtube.com/watch?v=AdOpT000003'
    media_id = _seed_media(url)
    dto = _dto(url, str(uuid.uuid4()), media_id)

    result = _persist_download_chain_state(
        dto, create_download_task=True, create_transcript_task=False
    )

    assert result is not None
    assert result[0] != dto.placeholder_task_id
    assert _download_rows(url)[0].status == TaskStatus.QUEUED


async def test_storage_quota_retires_placeholder_with_a_reason(test_database, monkeypatch):
    url = 'https://www.youtube.com/watch?v=AdOpT000004'
    task_id = _seed_placeholder(url)
    monkeypatch.setattr('tasks.media._check_storage_quota', lambda *_: True)

    create_download_and_transcript_chains_impl(
        {'url': url, 'media_type': 'VIDEO', 'placeholder_task_id': task_id}
    )

    record = _reload(task_id)
    assert record.status == TaskStatus.FAILED
    assert record.status_message == 'Storage limit reached'


async def test_guard_retires_a_placeholder_left_behind_by_a_raising_body(test_database):
    url = 'https://www.youtube.com/watch?v=AdOpT000005'
    task_id = _seed_placeholder(url)

    boom = RuntimeError('yt-dlp exploded')

    @guard_resolving_placeholders
    def _body(_ctx, _payload):
        raise boom

    with pytest.raises(RuntimeError):
        _body(None, {'url': url, 'placeholder_task_id': task_id})

    record = _reload(task_id)
    assert record.status == TaskStatus.SKIPPED
    assert record.status_message == 'Could not resolve this video'


async def test_dispatch_publishes_the_message_the_adopted_row_was_given(test_database):
    """The SSE text and the stored text must agree, or the Message cell rewords on reload.

    dispatch_download_chain only publishes its status message — the row's own copy comes
    from the adoption — so nothing but this keeps the two in step.
    """
    url = 'https://www.youtube.com/watch?v=AdOpT000007'
    task_id = _seed_placeholder(url)
    _seed_media(url)

    job = serialize_download_job(
        DownloadJobDTO(
            url=url,
            media_type=MediaType.VIDEO,
            placeholder_task_id=task_id,
            generate_transcript=False,
        )
    )

    with patch.object(tr_repo, 'dispatch_download_chain') as dispatch:
        create_download_and_transcript_chains_impl(job)

    assert dispatch.call_args.kwargs['download_status_msg'] == _reload(task_id).status_message


async def test_guard_leaves_an_adopted_placeholder_alone(test_database):
    """The guard is conditional on RESOLVING, so it can't clobber a successful chain."""
    url = 'https://www.youtube.com/watch?v=AdOpT000006'
    task_id = _seed_placeholder(url)
    tr_repo.sync_update_one(task_id, {'status': TaskStatus.QUEUED})

    @guard_resolving_placeholders
    def _body(_ctx, _payload):
        return 'ok'

    assert _body(None, {'url': url, 'placeholder_task_id': task_id}) == 'ok'
    assert _reload(task_id).status == TaskStatus.QUEUED


# ======================================================== router level (POST /ytdl/)

ROUTER_URL = 'https://www.youtube.com/watch?v=PlAcEhOlDr1'


def _task_for(url: str) -> TaskRecord | None:
    session = db.get_sync_session()
    try:
        return (
            session.execute(select(TaskRecord).where(TaskRecord.download_job_url == url))
            .scalars()
            .first()
        )
    finally:
        session.close()


def _post(client, url: str):
    return client.post(
        '/ytdl/',
        json={
            'url': url,
            'media_type': 'VIDEO',
            'audio_only': False,
            'download_playlist': False,
            'overwrite': False,
            'generate_transcript': False,
        },
    )


def _seed_blocking_task(url: str, task_id: str, task_status: TaskStatus) -> None:
    session = db.get_sync_session()
    try:
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type=TaskType.DOWNLOAD,
                status=task_status,
                media_type=MediaType.VIDEO,
                download_job_url=url,
            )
        )
        session.commit()
    finally:
        session.close()


async def test_submit_creates_resolving_placeholder(monkeypatch, authenticated_client):
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    response = _post(authenticated_client, ROUTER_URL)

    assert response.status_code == 201
    record = _task_for(ROUTER_URL)
    assert record is not None
    assert record.status == TaskStatus.RESOLVING
    assert record.task_type == TaskType.DOWNLOAD
    assert record.media_type == MediaType.VIDEO
    assert record.status_message == 'Fetching video metadata...'
    # Title falls back to the URL so the row isn't blank before metadata arrives
    assert record.title == ROUTER_URL
    assert response.json()['task_id'] == record.task_id

    # The pipeline gets the placeholder id, so the chain adopts this row
    submitted_jobs = mock_submit.call_args.args[0].args[0]
    assert submitted_jobs[0]['placeholder_task_id'] == record.task_id


async def test_placeholder_carries_payload_for_restart_recovery(monkeypatch, authenticated_client):
    monkeypatch.setattr('routers.ytdl_router.orch.submit', AsyncMock())

    url = 'https://www.youtube.com/watch?v=PlAcEhOlDr2'
    _post(authenticated_client, url)

    record = _task_for(url)
    # Both the pipeline and populate jobs are tracked=False, so this payload is the
    # only durable record of the request until the chain is persisted.
    assert record.pending_payload is not None
    assert record.pending_payload['url'] == url
    assert record.pending_payload['media_type'] == 'VIDEO'
    # Stamped before the insert: the payload is serialized at commit, so a resumed
    # populate that couldn't see its own id would insert a second download row against
    # the slot this one still holds.
    assert record.pending_payload['placeholder_task_id'] == record.task_id


async def test_playlist_submit_says_enumerating(monkeypatch, authenticated_client):
    monkeypatch.setattr('routers.ytdl_router.orch.submit', AsyncMock())

    url = 'https://www.youtube.com/playlist?list=PLpLaCeHoLdEr'
    authenticated_client.post(
        '/ytdl/',
        json={
            'url': url,
            'media_type': 'VIDEO',
            'audio_only': False,
            'download_playlist': True,
            'overwrite': False,
            'generate_transcript': False,
        },
    )

    assert _task_for(url).status_message == 'Enumerating playlist...'


async def test_resubmitting_a_cancelled_url_conflicts(monkeypatch, authenticated_client):
    """A cancelled row keeps holding the URL's slot, so the pipeline would drop this silently."""
    mock_submit = AsyncMock()
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    url = 'https://www.youtube.com/watch?v=PlAcEhOlDr3'
    _seed_blocking_task(url, 'cancelled-owner', TaskStatus.CANCELLED)

    response = _post(authenticated_client, url)

    assert response.status_code == 409
    detail = response.json()['detail']
    assert 'cancelled download' in detail['message'].lower()
    assert detail['task_id'] == 'cancelled-owner'
    assert mock_submit.await_count == 0, 'no point queueing work the chain will refuse'
    assert _task_for(url).task_id == 'cancelled-owner', 'no placeholder is created'


async def test_resubmitting_a_resolving_url_conflicts(monkeypatch, authenticated_client):
    """The in-flight placeholder blocks a double-submit before the DB index has to."""
    monkeypatch.setattr('routers.ytdl_router.orch.submit', AsyncMock())

    url = 'https://www.youtube.com/watch?v=PlAcEhOlDr4'
    _post(authenticated_client, url)
    response = _post(authenticated_client, url)

    assert response.status_code == 409
    assert response.json()['detail']['message'] == 'Download task already exists'


async def test_placeholder_yields_to_a_concurrent_winner(test_database):
    """Race backstop: the pre-check passed, then another submission took the URL.

    Reaching here means the loser should carry on without a row, not fail the request.
    """
    from routers.ytdl_router import _create_resolving_placeholder

    url = 'https://www.youtube.com/watch?v=PlAcEhOlDr5'
    _seed_blocking_task(url, 'race-winner', TaskStatus.QUEUED)
    job = {'url': url, 'media_type': 'VIDEO'}

    assert await _create_resolving_placeholder(job, MediaType.VIDEO, user_id=1) is None
    assert job['placeholder_task_id'] is None
