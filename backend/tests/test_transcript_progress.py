"""Tests for transcript generation progress tracking."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

import repositories.task_records as task_repo
from database import db
from models import MediaDetails, MediaType, TaskRecord, TaskStatus, TaskType
from services.transcript import generate_raw_segments, update_progress


@pytest.fixture
def task_record(clean_database):
    """Create a TaskRecord for testing."""
    session = db.get_sync_session()
    try:
        task = TaskRecord(
            task_id='test-task-id-123',
            task_type=TaskType.TRANSCRIPT_GENERATION,
            status=TaskStatus.IN_PROGRESS,
            percent_complete=0,
            status_message='Generating transcript...',
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task
    finally:
        session.close()


@pytest.fixture
def media_details(clean_database):
    """Create MediaDetails for testing."""
    session = db.get_sync_session()
    try:
        md = MediaDetails(
            url='https://www.youtube.com/watch?v=rgUrqGFxV3Q',
            media_type=MediaType.AUDIO,
            channel='Test Channel',
            title='Test Video',
            status=TaskStatus.COMPLETE,
            transcript_status=TaskStatus.IN_PROGRESS,
            transcript_progress=0.0,
        )
        session.add(md)
        session.commit()
        session.refresh(md)
        return md
    finally:
        session.close()


class TestUpdateProgress:
    """Tests for the update_progress function."""

    def test_update_progress_updates_task_record(self, clean_database, task_record, media_details):
        """Test that update_progress updates the TaskRecord percent_complete."""
        # Call update_progress
        update_progress(task_record.task_id, media_details.id, 50.0, 'Processing chunk 1/2')

        # Verify TaskRecord was updated
        updated_task = task_repo.sync_get_task_by_task_id(task_record.task_id)
        assert updated_task is not None
        assert updated_task.percent_complete == 50
        assert updated_task.status_message == 'Processing chunk 1/2'

    def test_update_progress_updates_media_details(
        self, clean_database, task_record, media_details
    ):
        """update_progress must update TaskRecord."""
        # Call update_progress
        update_progress(task_record.task_id, media_details.id, 75.0, 'Processing chunk 3/4')

        # Verify TaskRecord was updated (MediaDetails transcript_progress removed)
        # Progress is now tracked via TaskRecord only
        session = db.get_sync_session()
        try:
            from sqlmodel import select

            stmt = select(TaskRecord).where(TaskRecord.task_id == task_record.task_id)
            result = session.execute(stmt)
            updated_tr = result.scalar_one_or_none()
            assert updated_tr is not None
            assert updated_tr.percent_complete == 75
            assert updated_tr.status_message == 'Processing chunk 3/4'
        finally:
            session.close()

    def test_update_progress_rounds_to_int_for_task_record(
        self, clean_database, task_record, media_details
    ):
        """Test that percent_complete is stored as int in TaskRecord."""
        update_progress(task_record.task_id, media_details.id, 33.7, 'Processing...')

        updated_task = task_repo.sync_get_task_by_task_id(task_record.task_id)
        assert updated_task.percent_complete == 33  # Rounded to int


class TestGenerateTranscriptProgress:
    """Tests for progress tracking during transcript generation."""

    @patch('faster_whisper.WhisperModel')
    @patch('services.transcript.get_media_duration')
    @patch('os.path.exists')
    def test_generate_raw_segments_updates_progress_for_short_file(
        self,
        mock_exists,
        mock_duration,
        mock_whisper,
        clean_database,
        task_record,
        media_details,
    ):
        """Test that progress is updated to 100% for short files after transcription."""
        # Setup mocks
        mock_exists.return_value = True
        mock_duration.return_value = 300.0  # 5 minutes - short file

        # Mock whisper model and transcription
        mock_model = MagicMock()
        mock_whisper.return_value = mock_model

        # Create mock segments
        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 10.0
        mock_segment.text = 'Test transcript text'
        mock_model.transcribe.return_value = ([mock_segment], None)

        # Create a temp file path
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            temp_path = f.name

        try:
            # Call generate_raw_segments with task_id
            generate_raw_segments(
                temp_path,
                media_id=media_details.id,
                task_id=task_record.task_id,
                user_id=media_details.owner_id,
            )

            # Verify progress was updated to 100%
            updated_task = task_repo.sync_get_task_by_task_id(task_record.task_id)
            assert updated_task.percent_complete == 100
            assert updated_task.status_message == 'Transcription complete'
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch('faster_whisper.WhisperModel')
    @patch('services.transcript.get_media_duration')
    @patch('services.transcript.create_audio_chunks')
    @patch('os.path.exists')
    def test_generate_raw_segments_updates_progress_for_chunked_file(
        self,
        mock_exists,
        mock_chunks,
        mock_duration,
        mock_whisper,
        clean_database,
        task_record,
        media_details,
    ):
        """Test that progress is updated incrementally for long files processed in chunks."""
        # Setup mocks
        mock_exists.return_value = True
        mock_duration.return_value = 1800.0  # 30 minutes - long file, will be chunked

        # Mock chunk creation - 3 chunks
        temp_dir = tempfile.mkdtemp()
        chunk_paths = [
            (os.path.join(temp_dir, 'chunk_0.mp3'), 0.0),
            (os.path.join(temp_dir, 'chunk_1.mp3'), 600.0),
            (os.path.join(temp_dir, 'chunk_2.mp3'), 1200.0),
        ]
        # Create actual temp files for the chunks
        for chunk_path, _ in chunk_paths:
            with open(chunk_path, 'w') as f:
                f.write('dummy')

        mock_chunks.return_value = (chunk_paths, temp_dir)

        # Mock whisper model
        mock_model = MagicMock()
        mock_whisper.return_value = mock_model

        # Mock segment for each chunk
        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 10.0
        mock_segment.text = 'Test text'
        mock_model.transcribe.return_value = ([mock_segment], None)

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            temp_path = f.name

        try:
            generate_raw_segments(
                temp_path,
                media_id=media_details.id,
                task_id=task_record.task_id,
                user_id=media_details.owner_id,
            )

            # Verify final state in database - should be 100% after all chunks processed
            updated_task = task_repo.sync_get_task_by_task_id(task_record.task_id)
            assert updated_task.percent_complete == 100
            assert updated_task.status_message == 'Transcription complete'

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            # Note: temp_dir is already cleaned up by generate_raw_segments's finally block

    @patch('faster_whisper.WhisperModel')
    @patch('services.transcript.get_media_duration')
    @patch('os.path.exists')
    def test_generate_raw_segments_without_task_id_does_not_update_progress(
        self, mock_exists, mock_duration, mock_whisper, clean_database, media_details
    ):
        """Test that no progress updates happen when task_id is None."""
        mock_exists.return_value = True
        mock_duration.return_value = 300.0

        mock_model = MagicMock()
        mock_whisper.return_value = mock_model
        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 10.0
        mock_segment.text = 'Test'
        mock_model.transcribe.return_value = ([mock_segment], None)

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            temp_path = f.name

        try:
            with patch('services.transcript.update_progress') as mock_update:
                # Call without task_id
                generate_raw_segments(temp_path, media_id=media_details.id, task_id=None)

                # Verify update_progress was never called
                mock_update.assert_not_called()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
