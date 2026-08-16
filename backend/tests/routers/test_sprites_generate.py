"""POST /media/{id}/sprites/generate — the manual regeneration endpoint."""

from unittest.mock import patch

import pytest

from database import db
from models import MediaDetails, MediaType, TaskStatus, TaskType
from repositories import task_records


@pytest.fixture
def video_media(tmp_path):
    f = tmp_path / 'movie.mp4'
    f.write_bytes(b'\x00' * 2048)
    session = db.get_sync_session()
    try:
        md = session.get(MediaDetails, 1)
        md.file_path = str(f)
        md.media_type = MediaType.VIDEO
        md.duration = 1800.0
        session.add(md)
        session.commit()
        return md.id
    finally:
        session.close()


@pytest.fixture
def no_orchestrator():
    """The orchestrator isn't running under TestClient; the row is what matters."""
    with patch('orchestrator.orch.submit_from_thread'):
        yield


def test_generate_creates_a_tracked_task(authenticated_client, video_media, no_orchestrator):
    resp = authenticated_client.post(f'/media/{video_media}/sprites/generate')

    assert resp.status_code == 200
    body = resp.json()
    assert body['status'] == 'queued'
    assert body['task_id']

    task = task_records.sync_get_task_by_task_id(body['task_id'])
    assert task.task_type == TaskType.SPRITE_GENERATION
    assert task.status == TaskStatus.QUEUED
    assert task.status_message == 'Waiting to generate sprite sheet...'
    # Set so ix_task_records_active_unique dedups, and so recovery/retry can
    # re-resolve the media row.
    assert task.download_job_url is not None


def test_generate_twice_reuses_the_active_task(authenticated_client, video_media, no_orchestrator):
    first = authenticated_client.post(f'/media/{video_media}/sprites/generate').json()
    second = authenticated_client.post(f'/media/{video_media}/sprites/generate').json()

    assert first['task_id'] == second['task_id']


def test_generate_rejects_audio(authenticated_client):
    session = db.get_sync_session()
    try:
        md = session.get(MediaDetails, 1)
        md.media_type = MediaType.AUDIO
        session.add(md)
        session.commit()
    finally:
        session.close()

    resp = authenticated_client.post('/media/1/sprites/generate')
    assert resp.status_code == 400
    assert 'only for videos' in resp.json()['detail']
