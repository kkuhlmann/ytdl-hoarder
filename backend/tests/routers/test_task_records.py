from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from database import db
from models import MediaType, TaskRecord, TaskStatus, TaskType


def test_get_all_task_records(authenticated_client):
    response = authenticated_client.get('/tasks')
    assert response.status_code == 200
    data = response.json()
    assert 'count_records' in data
    assert 'records' in data
    assert data['count_records'] >= 6  # At least 6 test task records


def test_get_all_task_records_with_status_filter(authenticated_client):
    response = authenticated_client.get('/tasks?statuses=COMPLETE')
    assert response.status_code == 200
    data = response.json()
    assert data['count_records'] >= 2  # At least 2 COMPLETE tasks
    assert all(r['status'] == 'COMPLETE' for r in data['records'])


def test_get_all_task_records_with_multiple_statuses(authenticated_client):
    response = authenticated_client.get('/tasks?statuses=QUEUED,IN_PROGRESS')
    assert response.status_code == 200
    data = response.json()
    assert all(r['status'] in ['QUEUED', 'IN_PROGRESS'] for r in data['records'])


def test_get_all_task_records_with_pagination(authenticated_client):
    # Get first page
    response1 = authenticated_client.get('/tasks?page=1&page_size=2')
    assert response1.status_code == 200
    page1 = response1.json()
    assert len(page1['records']) == 2

    # Get second page
    response2 = authenticated_client.get('/tasks?page=2&page_size=2')
    assert response2.status_code == 200
    page2 = response2.json()

    # Verify different records
    page1_ids = [r['id'] for r in page1['records']]
    page2_ids = [r['id'] for r in page2['records']]
    assert not any(id in page1_ids for id in page2_ids)


def test_get_all_task_records_with_sorting(authenticated_client):
    response = authenticated_client.get('/tasks?sort_by=created_at&sort_direction=asc')
    assert response.status_code == 200
    data = response.json()
    assert len(data['records']) > 0


def test_get_task_status(authenticated_client):
    # No orchestrator running in tests: falls back to the TaskRecord status
    # (COMPLETE → 'SUCCESS').
    response = authenticated_client.get('/tasks/task-download-complete-1')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'SUCCESS'


def test_get_task_status_unknown_id(authenticated_client):
    # Unknown ids report PENDING (jobStatusService keeps polling until
    # SUCCESS/FAILURE).
    response = authenticated_client.get('/tasks/completely-unknown-task-id')
    assert response.status_code == 200
    assert response.json()['status'] == 'PENDING'


def test_get_task_status_rejects_other_users_task(authenticated_client):
    """Unlike its siblings, this route had no ownership check, so any approved
    user could probe arbitrary task ids and read other users' job states.
    """
    from fastapi.testclient import TestClient

    from main import app

    reg = authenticated_client.post(
        '/auth/register', json={'username': 'taskprobe', 'password': 'pass123'}
    )
    other_id = reg.json()['id']
    authenticated_client.post(f'/auth/users/{other_id}/approve')

    other = TestClient(app)
    other.post('/auth/login', json={'username': 'taskprobe', 'password': 'pass123'})

    # Owned by the admin fixture user, not by 'taskprobe'.
    assert other.get('/tasks/task-download-complete-1').status_code == 404
    # The owner still sees it.
    assert authenticated_client.get('/tasks/task-download-complete-1').status_code == 200


def test_get_task_status_untracked_job_is_owner_scoped(authenticated_client):
    """add-subscription jobs have no TaskRecord, so ownership comes from the
    orchestrator's in-memory result registry instead.
    """
    from fastapi.testclient import TestClient

    from main import app
    from orchestrator import orch

    reg = authenticated_client.post(
        '/auth/register', json={'username': 'untracked', 'password': 'pass123'}
    )
    other_id = reg.json()['id']
    authenticated_client.post(f'/auth/users/{other_id}/approve')
    other = TestClient(app)
    other.post('/auth/login', json={'username': 'untracked', 'password': 'pass123'})

    admin_id = next(
        u['id'] for u in authenticated_client.get('/auth/users').json() if u['is_admin']
    )
    orch._set_result('untracked-job-1', 'STARTED', user_id=admin_id)

    assert other.get('/tasks/untracked-job-1').status_code == 404
    assert authenticated_client.get('/tasks/untracked-job-1').json()['status'] == 'STARTED'

    # A state transition must not drop the owner recorded at submit time.
    orch._set_result('untracked-job-1', 'SUCCESS')
    assert other.get('/tasks/untracked-job-1').status_code == 404


@patch('routers.task_records.cleanup_task_files')
@patch('routers.task_records.orch', autospec=True)
def test_revoke_task(mock_orch, mock_cleanup, authenticated_client):
    mock_orch.cancel.return_value = 'dequeued'
    mock_cleanup.return_value = 0

    response = authenticated_client.delete('/tasks/task-download-queued-5')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'cancelled'
    assert data['task_id'] == 'task-download-queued-5'
    assert 'downstream_tasks_cancelled' in data
    mock_orch.cancel.assert_awaited_once_with('task-download-queued-5')


@patch('routers.task_records.cleanup_task_files')
@patch('routers.task_records.orch', autospec=True)
def test_revoke_task_not_found(mock_orch, mock_cleanup, authenticated_client):
    mock_orch.cancel.return_value = 'unknown'

    response = authenticated_client.delete('/tasks/nonexistent-task-id')
    assert response.status_code == 404
    assert 'not found' in response.json()['detail'].lower()


async def test_retry_task_not_found(authenticated_client):
    response = authenticated_client.post('/tasks/9999/retry', json={'retry_downstream': True})
    assert response.status_code == 404
    assert 'not found' in response.json()['detail'].lower()


async def test_retry_task_not_retryable(authenticated_client):
    # COMPLETE tasks cannot be retried
    response = authenticated_client.post('/tasks/1/retry', json={'retry_downstream': True})
    assert response.status_code == 400
    assert 'cannot be retried' in response.json()['detail'].lower()


@patch('routers.task_records.cleanup_task_files')
@patch('routers.task_records.orch', autospec=True)
def test_bulk_cancel_tasks(mock_orch, mock_cleanup, authenticated_client):
    # autospec so a call that doesn't match Orchestrator.cancel's real signature fails here
    # rather than at runtime.
    mock_orch.cancel.return_value = 'dequeued'
    mock_cleanup.return_value = 0

    # Create tasks to cancel
    from repositories import task_records as tr_repo

    tr_repo.sync_insert_many_tasks(
        [
            TaskRecord(
                task_id='router-bulk-cancel-1',
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.QUEUED,
            ),
            TaskRecord(
                task_id='router-bulk-cancel-2',
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.QUEUED,
            ),
        ]
    )

    response = authenticated_client.post(
        '/tasks/bulk/cancel',
        json={'task_ids': ['router-bulk-cancel-1', 'router-bulk-cancel-2']},
    )
    assert response.status_code == 200
    data = response.json()
    assert data['cancelled_count'] == 2
    assert 'errors' in data


@patch('routers.task_records.cleanup_task_files')
@patch('routers.task_records.orch', autospec=True)
def test_bulk_cancel_resolving_skips_file_cleanup(mock_orch, mock_cleanup, authenticated_client):
    # A RESOLVING row's title is the raw submitted URL; its download never dispatched,
    # so the glob cleanup must not run for it (mirrors revoke_task's guard).
    mock_orch.cancel.return_value = 'dequeued'
    mock_cleanup.return_value = 0

    from repositories import task_records as tr_repo

    tr_repo.sync_insert_many_tasks(
        [
            TaskRecord(
                task_id='router-bulk-cancel-resolving',
                task_type=TaskType.DOWNLOAD,
                status=TaskStatus.RESOLVING,
                title='https://example.com/*',
            ),
        ]
    )

    response = authenticated_client.post(
        '/tasks/bulk/cancel',
        json={'task_ids': ['router-bulk-cancel-resolving']},
    )
    assert response.status_code == 200
    mock_cleanup.assert_not_called()


def test_bulk_delete_tasks(authenticated_client):
    """Test bulk delete of task records.

    Note: Uses existing test data (tasks 1-6) created by the fixture.
    We'll create and delete new tasks to avoid affecting other tests.
    """
    # First, verify we can get tasks (to ensure db is set up)
    response = authenticated_client.get('/tasks')
    assert response.status_code == 200

    # Test against pre-populated task records
    # Instead, test bulk delete with non-existent IDs (should return 0 deleted)
    response = authenticated_client.request(
        method='DELETE',
        url='/tasks/bulk',
        json={'record_ids': [9999, 9998]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data['deleted_count'] == 0  # Non-existent IDs


@patch('routers.task_records.cleanup_task_files')
@patch('routers.task_records.orch', autospec=True)
def test_bulk_delete_cancels_a_still_active_task(mock_orch, mock_cleanup, authenticated_client):
    """Delete means gone: a queued job must not keep running behind a hidden row."""
    mock_orch.cancel.return_value = 'dequeued'
    mock_cleanup.return_value = 0

    from repositories import task_records as tr_repo

    record = TaskRecord(
        task_id='router-bulk-delete-queued',
        task_type=TaskType.DOWNLOAD,
        status=TaskStatus.QUEUED,
        download_job_url='https://www.youtube.com/watch?v=bulkdel1',
        media_type=MediaType.VIDEO,
    )
    tr_repo.sync_insert_task(record)

    response = authenticated_client.request(
        method='DELETE',
        url='/tasks/bulk',
        json={'record_ids': [record.id]},
    )

    assert response.status_code == 200
    assert response.json()['deleted_count'] == 1
    mock_orch.cancel.assert_awaited_with('router-bulk-delete-queued')

    session = db.get_sync_session()
    try:
        stored = session.get(TaskRecord, record.id)
        assert stored.deleted_at is not None
        assert stored.status == TaskStatus.DELETED
    finally:
        session.close()


def test_bulk_delete_tasks_empty(authenticated_client):
    response = authenticated_client.request(
        method='DELETE',
        url='/tasks/bulk',
        json={'record_ids': []},
    )
    assert response.status_code == 200
    data = response.json()
    assert data['deleted_count'] == 0


def test_completed_24h_uses_updated_at(authenticated_client):
    """Verify that 'completed_24h' stat counts tasks by updated_at, not created_at.

    A task created 3 days ago but completed (updated) recently should appear
    in the completed_24h count.
    """
    from repositories import task_records as tr_repo

    now = datetime.now(UTC).replace(tzinfo=None)
    three_days_ago = now - timedelta(days=3)

    tr_repo.sync_insert_task(
        TaskRecord(
            task_id='task-old-created-recent-complete',
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.COMPLETE,
            percent_complete=100,
            title='Old task completed recently',
            channel='Test Channel',
            media_type=MediaType.AUDIO,
            created_at=three_days_ago,
            updated_at=now,
        )
    )

    response = authenticated_client.get('/tasks/stats')
    assert response.status_code == 200
    data = response.json()
    # The task has an old created_at but recent updated_at, so it must be counted
    assert data['completed_24h'] >= 1


def test_task_stats_shape_and_counts(authenticated_client):
    stats = authenticated_client.get('/tasks/stats').json()
    assert stats == {
        'queued_total': 1,
        'queued_downloads': 1,
        'queued_transcripts': 0,
        'processing': 1,
        'failed': 1,
        'retry': 0,
        'not_ready': 0,
        'completed_24h': 2,
    }


def test_has_downstream_tasks_flags(authenticated_client):
    records = authenticated_client.get('/tasks').json()['records']
    by_id = {r['task_id']: r for r in records}
    assert by_id['task-download-complete-1']['has_downstream_tasks'] is True
    assert by_id['task-download-failed-2']['has_downstream_tasks'] is True
    assert by_id['task-transcript-complete-3']['has_downstream_tasks'] is False


def test_task_stats_includes_not_ready(authenticated_client):
    """The stats payload must expose a not_ready bucket for the frontend tile."""
    response = authenticated_client.get('/tasks/stats')
    assert response.status_code == 200
    data = response.json()
    assert 'not_ready' in data
    assert isinstance(data['not_ready'], int)


def test_bulk_retry_tasks_with_errors(authenticated_client):
    """Test bulk retry returns errors for non-retryable tasks (COMPLETE status)."""
    # Tasks 1 and 3 are COMPLETE status - they cannot be retried
    response = authenticated_client.post(
        '/tasks/bulk/retry',
        json={
            'record_ids': [1, 3],
            'retry_downstream': True,
            'overwrite': False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    # Should have errors since tasks with ids 1 and 3 are COMPLETE (not retryable)
    assert 'errors' in data
    assert len(data['errors']) == 2


def test_unauthenticated_rejected(test_database):
    """Unauthenticated requests to task endpoints return 401."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    response = client.get('/tasks')
    assert response.status_code == 401


# --- Retry success-path tests ---


def _create_failed_download_task_with_job(session, user_id: int) -> int:
    """Insert a FAILED download task with linked MediaDetails + DownloadJob.

    Returns the TaskRecord.id (database primary key).
    """
    from models import DownloadJob, JobType, MediaDetails

    task = TaskRecord(
        task_id='task-retry-download-failed',
        task_type=TaskType.DOWNLOAD,
        status=TaskStatus.FAILED,
        percent_complete=50,
        status_message='Download failed: network error',
        title='Retry Test Video',
        channel='Retry Channel',
        media_type=MediaType.AUDIO,
        download_job_url='https://www.youtube.com/watch?v=retry123',
        user_id=user_id,
    )
    session.add(task)
    session.flush()
    task_record_id = task.id

    md = MediaDetails(
        url='https://www.youtube.com/watch?v=retry123',
        media_type=MediaType.AUDIO,
        channel='Retry Channel',
        title='Retry Test Video',
        status=TaskStatus.FAILED,
        download_task_record_id=task_record_id,
        owner_id=user_id,
    )
    session.add(md)
    session.flush()

    dj = DownloadJob(
        url='https://www.youtube.com/watch?v=retry123',
        audio_only=True,
        download_playlist=False,
        overwrite=False,
        media_type=MediaType.AUDIO,
        job_type=JobType.NORMAL_DOWNLOAD,
        media_details_id=md.id,
        user_id=user_id,
    )
    session.add(dj)
    session.commit()

    return task_record_id


def _create_cancelled_transcript_task_with_media(session, user_id: int) -> int:
    """Insert a CANCELLED transcript task with linked MediaDetails.

    Returns the TaskRecord.id (database primary key).
    """
    from models import MediaDetails

    task = TaskRecord(
        task_id='task-retry-transcript-cancelled',
        task_type=TaskType.TRANSCRIPT_GENERATION,
        status=TaskStatus.CANCELLED,
        percent_complete=0,
        title='Transcript Test Video',
        channel='Transcript Channel',
        media_type=MediaType.AUDIO,
        user_id=user_id,
    )
    session.add(task)
    session.flush()
    task_record_id = task.id

    md = MediaDetails(
        url='https://www.youtube.com/watch?v=transcript123',
        media_type=MediaType.AUDIO,
        channel='Transcript Channel',
        title='Transcript Test Video',
        status=TaskStatus.COMPLETE,
        file_path='/mnt/audio/transcript_test.mp3',
        transcript_task_record_id=task_record_id,
        owner_id=user_id,
    )
    session.add(md)
    session.commit()

    return task_record_id


def _get_user_id_from_client(client) -> int:
    """Get the user ID from an authenticated client by calling the auth endpoint."""
    resp = client.get('/auth/me')
    return resp.json()['id']


@patch('repositories.task_records.retry.dispatch_download_chain')
@patch('repositories.task_records.retry._cancel_and_reassign_task_id', new_callable=AsyncMock)
def test_retry_failed_download_task(mock_revoke, mock_dispatch, authenticated_client):
    """Happy path: retry a FAILED download task, verify 200 + new task_id returned."""
    user_id = _get_user_id_from_client(authenticated_client)

    session = db.get_sync_session()
    try:
        record_id = _create_failed_download_task_with_job(session, user_id)
    finally:
        session.close()

    # Mock _revoke_and_reassign_task_id to return a predictable new task ID
    mock_revoke.return_value = ('task-retry-download-failed', 'new-download-task-id')

    response = authenticated_client.post(
        f'/tasks/{record_id}/retry',
        json={'retry_downstream': False, 'overwrite': False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'retrying'
    assert data['retried_count'] == 1
    assert 'new-download-task-id' in data['task_ids']
    mock_dispatch.assert_called_once()


@patch('repositories.task_records.retry._dispatch_transcript_task')
@patch('repositories.task_records.retry._cancel_and_reassign_task_id', new_callable=AsyncMock)
def test_retry_cancelled_transcript_task(mock_revoke, mock_dispatch, authenticated_client):
    """Happy path: retry a CANCELLED transcript task."""
    user_id = _get_user_id_from_client(authenticated_client)

    session = db.get_sync_session()
    try:
        record_id = _create_cancelled_transcript_task_with_media(session, user_id)
    finally:
        session.close()

    mock_revoke.return_value = ('task-retry-transcript-cancelled', 'new-transcript-task-id')

    response = authenticated_client.post(
        f'/tasks/{record_id}/retry',
        json={'retry_downstream': False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'retrying'
    assert data['retried_count'] == 1
    assert 'new-transcript-task-id' in data['task_ids']
    mock_dispatch.assert_called_once()


def test_retry_task_incomplete_upstream(authenticated_client):
    """400 when upstream tasks aren't COMPLETE."""
    user_id = _get_user_id_from_client(authenticated_client)

    # Task id=4 is UPSTREAM_FAILED with upstream_task_ids=['task-download-failed-2']
    # Task 'task-download-failed-2' is FAILED (not COMPLETE), so retry should be blocked.
    # But first we need to make id=4 a retryable status — it's UPSTREAM_FAILED which is
    # not in RETRYABLE_STATUSES. Let's create a FAILED transcript with incomplete upstream.
    from repositories import task_records as tr_repo

    task_record = tr_repo.sync_insert_task(
        TaskRecord(
            task_id='task-transcript-incomplete-upstream',
            task_type=TaskType.TRANSCRIPT_GENERATION,
            status=TaskStatus.FAILED,
            upstream_task_ids=['task-download-failed-2'],
            title='Transcript with incomplete upstream',
            channel='Test Channel',
            media_type=MediaType.AUDIO,
            user_id=user_id,
        )
    )

    response = authenticated_client.post(
        f'/tasks/{task_record.id}/retry',
        json={'retry_downstream': False},
    )

    assert response.status_code == 400
    assert 'upstream tasks' in response.json()['detail'].lower()


@patch('repositories.task_records.retry.dispatch_download_chain')
@patch('repositories.task_records.retry._cancel_and_reassign_task_id', new_callable=AsyncMock)
def test_retry_download_with_overwrite(mock_revoke, mock_dispatch, authenticated_client):
    """Verify overwrite=True flows through to serialized data."""
    user_id = _get_user_id_from_client(authenticated_client)

    session = db.get_sync_session()
    try:
        record_id = _create_failed_download_task_with_job(session, user_id)
    finally:
        session.close()

    mock_revoke.return_value = ('task-retry-download-failed', 'new-overwrite-task-id')

    response = authenticated_client.post(
        f'/tasks/{record_id}/retry',
        json={'retry_downstream': False, 'overwrite': True},
    )

    assert response.status_code == 200
    # Verify dispatch was called with overwrite=True in the download_data
    call_kwargs = mock_dispatch.call_args
    download_data = call_kwargs.kwargs.get('download_data') or call_kwargs[1].get('download_data')
    assert download_data['overwrite'] is True


@patch('repositories.task_records.retry.dispatch_download_chain')
@patch('repositories.task_records.retry._cancel_and_reassign_task_id', new_callable=AsyncMock)
def test_retry_download_with_downstream(mock_revoke, mock_dispatch, authenticated_client):
    """Verify downstream transcript gets chained when retry_downstream=True."""
    user_id = _get_user_id_from_client(authenticated_client)

    # Create a FAILED download task with MediaDetails + DownloadJob
    session = db.get_sync_session()
    try:
        task = TaskRecord(
            task_id='task-download-with-downstream',
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.FAILED,
            title='Download With Downstream',
            channel='Test Channel',
            media_type=MediaType.AUDIO,
            download_job_url='https://www.youtube.com/watch?v=downstream123',
            user_id=user_id,
        )
        session.add(task)
        session.flush()
        download_record_id = task.id

        from models import DownloadJob, JobType, MediaDetails

        md = MediaDetails(
            url='https://www.youtube.com/watch?v=downstream123',
            media_type=MediaType.AUDIO,
            channel='Test Channel',
            title='Download With Downstream',
            status=TaskStatus.FAILED,
            download_task_record_id=download_record_id,
            owner_id=user_id,
        )
        session.add(md)
        session.flush()

        dj = DownloadJob(
            url='https://www.youtube.com/watch?v=downstream123',
            audio_only=True,
            download_playlist=False,
            overwrite=False,
            media_type=MediaType.AUDIO,
            job_type=JobType.NORMAL_DOWNLOAD,
            media_details_id=md.id,
            user_id=user_id,
        )
        session.add(dj)

        # Create a downstream transcript task with UPSTREAM_FAILED
        transcript_task = TaskRecord(
            task_id='task-transcript-downstream',
            task_type=TaskType.TRANSCRIPT_GENERATION,
            status=TaskStatus.UPSTREAM_FAILED,
            upstream_task_ids=['task-download-with-downstream'],
            title='Download With Downstream',
            channel='Test Channel',
            media_type=MediaType.AUDIO,
            user_id=user_id,
        )
        session.add(transcript_task)
        session.commit()
    finally:
        session.close()

    mock_revoke.return_value = ('task-download-with-downstream', 'new-download-chained-id')

    response = authenticated_client.post(
        f'/tasks/{download_record_id}/retry',
        json={'retry_downstream': True},
    )

    assert response.status_code == 200
    data = response.json()
    # Should have retried the download + chained transcript = 2
    assert data['retried_count'] == 2
    assert 'new-download-chained-id' in data['task_ids']
    assert len(data['task_ids']) == 2

    # dispatch_download_chain should be called with a transcript_task_id
    call_kwargs = mock_dispatch.call_args
    transcript_task_id = call_kwargs.kwargs.get('transcript_task_id') or call_kwargs[1].get(
        'transcript_task_id'
    )
    assert transcript_task_id is not None


def test_retry_task_no_download_job(authenticated_client):
    """404 when download job is missing for a FAILED download task."""
    user_id = _get_user_id_from_client(authenticated_client)
    from repositories import task_records as tr_repo

    # FAILED download task with NO linked MediaDetails/DownloadJob
    task_record = tr_repo.sync_insert_task(
        TaskRecord(
            task_id='task-download-no-job',
            task_type=TaskType.DOWNLOAD,
            status=TaskStatus.FAILED,
            title='Download With No Job',
            channel='Test Channel',
            media_type=MediaType.AUDIO,
            user_id=user_id,
        )
    )

    response = authenticated_client.post(
        f'/tasks/{task_record.id}/retry',
        json={'retry_downstream': False},
    )

    assert response.status_code == 404
    assert 'no mediadetails found' in response.json()['detail'].lower()


def test_retry_task_no_media_details(authenticated_client):
    """404 when media details missing for a FAILED transcript task."""
    user_id = _get_user_id_from_client(authenticated_client)
    from repositories import task_records as tr_repo

    # FAILED transcript task with NO linked MediaDetails
    task_record = tr_repo.sync_insert_task(
        TaskRecord(
            task_id='task-transcript-no-media',
            task_type=TaskType.TRANSCRIPT_GENERATION,
            status=TaskStatus.FAILED,
            title='Transcript With No Media',
            channel='Test Channel',
            media_type=MediaType.AUDIO,
            user_id=user_id,
        )
    )

    response = authenticated_client.post(
        f'/tasks/{task_record.id}/retry',
        json={'retry_downstream': False},
    )

    assert response.status_code == 404
    assert 'no mediadetails found' in response.json()['detail'].lower()
