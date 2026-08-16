from unittest.mock import AsyncMock

from repositories.task_records import DIRECT_DOWNLOAD_PRIORITY


async def test_create_download(monkeypatch, authenticated_client):
    """Test the /ytdl endpoint for creating downloads."""
    # Mock the orchestrator submit to avoid actually queuing the pipeline job
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    response = authenticated_client.post(
        '/ytdl/',
        json={
            'url': 'https://www.youtube.com/watch?v=rgUrqGFxV3Q',
            'audio_only': True,
            'download_playlist': False,
            'overwrite': False,
            'generate_transcript': False,
        },
    )
    # Should return 201 Created
    assert response.status_code == 201
    # Verify the direct-download pipeline job was submitted
    assert mock_submit.await_count == 1
    spec = mock_submit.await_args.args[0]
    assert spec.job_name == 'direct_download_pipeline'
    assert spec.args[0][0]['url'] == 'https://www.youtube.com/watch?v=rgUrqGFxV3Q'
    assert spec.priority == DIRECT_DOWNLOAD_PRIORITY, (
        'a manually-submitted download must outrank subscription fan-out'
    )


def test_unauthenticated_rejected(test_database):
    """Unauthenticated requests to ytdl endpoints return 401."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    response = client.post(
        '/ytdl/',
        json={
            'url': 'https://www.youtube.com/watch?v=rgUrqGFxV3Q',
            'audio_only': True,
            'download_playlist': False,
            'overwrite': False,
            'generate_transcript': False,
        },
    )
    assert response.status_code == 401


async def test_create_download_ignores_server_managed_fields(monkeypatch, authenticated_client):
    """POST /ytdl/ must not accept server-managed columns from the client.

    subscription_id flows into shared-access grants for the subscription's users and
    existing_media_details_id skips MediaDetails persistence, so a client setting
    either would corrupt the chain. The request schema ignores them.
    """
    mock_submit = AsyncMock(return_value='pipeline-task-id')
    monkeypatch.setattr('routers.ytdl_router.orch.submit', mock_submit)

    response = authenticated_client.post(
        '/ytdl/',
        json={
            'url': 'https://www.youtube.com/watch?v=maSs1gnmnT0',
            'audio_only': True,
            'subscription_id': 123,
            'existing_media_details_id': 456,
            'media_details_id': 789,
            'id': 42,
            'user_id': 999,
            'job_type': 'CHANNEL_SUBSCRIPTION',
        },
    )
    assert response.status_code == 201

    job = mock_submit.await_args.args[0].args[0][0]
    assert job.get('subscription_id') is None
    assert job.get('existing_media_details_id') is None
    assert job.get('media_details_id') is None
    assert job.get('job_type') == 'NORMAL_DOWNLOAD'
    assert job.get('user_id') != 999
