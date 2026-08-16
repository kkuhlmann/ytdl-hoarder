"""Tests for cooperative cancellation of transcript generation.

A running Whisper call cannot be interrupted mid-C-call, so the chunk loop polls
the TaskRecord status and raises TranscriptCancelled when it sees CANCELLED, which
the job body translates into JobCancelled.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

import repositories.task_records as task_repo
from database import db
from models import MediaDetails, MediaType, TaskRecord, TaskStatus, TaskType
from services.transcript import (
    TranscriptCancelled,
    _check_transcript_cancelled,
    generate_raw_segments,
)


@pytest.fixture
def task_record(clean_database):
    """Create a TaskRecord in IN_PROGRESS state for testing."""
    session = db.get_sync_session()
    try:
        task = TaskRecord(
            task_id='test-transcript-task-cancel',
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
            url='https://www.youtube.com/watch?v=cancel-test',
            media_type=MediaType.AUDIO,
            channel='Cancel Channel',
            title='Cancel Test Video',
            status=TaskStatus.COMPLETE,
            transcript_status=TaskStatus.IN_PROGRESS,
        )
        session.add(md)
        session.commit()
        session.refresh(md)
        return md
    finally:
        session.close()


def _set_cancelled(task_id: str) -> None:
    """Flip a TaskRecord's status to CANCELLED (mirrors the real cancel endpoint)."""
    task_repo.sync_update_one(task_id, {'status': TaskStatus.CANCELLED})


class TestCheckTranscriptCancelled:
    """Tests for the _check_transcript_cancelled helper."""

    def test_returns_silently_when_task_id_is_none(self, clean_database):
        """None task_id is a no-op (used for local/untracked transcription runs)."""
        _check_transcript_cancelled(None)  # should not raise

    def test_returns_silently_when_task_not_cancelled(self, clean_database, task_record):
        """IN_PROGRESS task should not trigger cancellation."""
        _check_transcript_cancelled(task_record.task_id)  # should not raise

    def test_raises_when_task_cancelled(self, clean_database, task_record):
        """CANCELLED task should raise TranscriptCancelled."""
        _set_cancelled(task_record.task_id)
        with pytest.raises(TranscriptCancelled, match=task_record.task_id):
            _check_transcript_cancelled(task_record.task_id)

    def test_returns_silently_when_task_record_missing(self, clean_database):
        """A task_id that has no TaskRecord is treated as not-cancelled."""
        _check_transcript_cancelled('no-such-task-id')  # should not raise


class TestGenerateRawSegmentsCancellation:
    """Tests for cooperative cancellation inside generate_raw_segments."""

    @patch('faster_whisper.WhisperModel')
    @patch('services.transcript.get_media_duration')
    @patch('services.transcript.create_audio_chunks')
    @patch('os.path.exists')
    def test_chunked_path_cancels_mid_loop(
        self,
        mock_exists,
        mock_chunks,
        mock_duration,
        mock_whisper,
        clean_database,
        task_record,
        media_details,
    ):
        """Chunked path: cancellation between chunks raises TranscriptCancelled
        and stops further chunk processing."""
        mock_exists.return_value = True
        mock_duration.return_value = 1800.0  # 30 min forces chunked branch

        temp_dir = tempfile.mkdtemp(prefix='transcript_cancel_test_')
        chunk_paths = [
            (os.path.join(temp_dir, 'chunk_0.mp3'), 0.0),
            (os.path.join(temp_dir, 'chunk_1.mp3'), 600.0),
            (os.path.join(temp_dir, 'chunk_2.mp3'), 1200.0),
        ]
        for chunk_path, _ in chunk_paths:
            with open(chunk_path, 'w') as f:
                f.write('dummy')
        mock_chunks.return_value = (chunk_paths, temp_dir)

        mock_model = MagicMock()
        mock_whisper.return_value = mock_model

        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 10.0
        mock_segment.text = 'chunk text'

        # After the first chunk transcribes successfully, flip the TaskRecord to CANCELLED
        # so the next iteration's _check_transcript_cancelled fires.
        transcribe_call_count = {'n': 0}

        def transcribe_side_effect(*args, **kwargs):
            transcribe_call_count['n'] += 1
            if transcribe_call_count['n'] == 1:
                _set_cancelled(task_record.task_id)
            return ([mock_segment], None)

        mock_model.transcribe.side_effect = transcribe_side_effect

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            temp_path = f.name

        try:
            with pytest.raises(TranscriptCancelled, match=task_record.task_id):
                generate_raw_segments(
                    temp_path,
                    media_id=media_details.id,
                    task_id=task_record.task_id,
                )
            # Exactly one chunk transcribed before the next iteration's check fired.
            assert transcribe_call_count['n'] == 1
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch('faster_whisper.WhisperModel')
    @patch('services.transcript.get_media_duration')
    @patch('os.path.exists')
    def test_short_file_path_cancels_before_transcribe(
        self,
        mock_exists,
        mock_duration,
        mock_whisper,
        clean_database,
        task_record,
        media_details,
    ):
        """Short-file path: pre-cancelled task should raise before transcribe runs."""
        mock_exists.return_value = True
        mock_duration.return_value = 300.0  # 5 min — short file branch

        mock_model = MagicMock()
        mock_whisper.return_value = mock_model

        _set_cancelled(task_record.task_id)

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            temp_path = f.name

        try:
            with pytest.raises(TranscriptCancelled, match=task_record.task_id):
                generate_raw_segments(
                    temp_path,
                    media_id=media_details.id,
                    task_id=task_record.task_id,
                )
            # The WhisperModel may be instantiated (we check before load AND before
            # transcribe), but model.transcribe() must never run.
            mock_model.transcribe.assert_not_called()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch('faster_whisper.WhisperModel')
    @patch('services.transcript.get_media_duration')
    @patch('os.path.exists')
    def test_pre_cancelled_exits_before_model_load(
        self,
        mock_exists,
        mock_duration,
        mock_whisper,
        clean_database,
        task_record,
        media_details,
    ):
        """If the task is already cancelled when generate_raw_segments is entered,
        the expensive WhisperModel load should be skipped entirely."""
        mock_exists.return_value = True
        mock_duration.return_value = 300.0

        _set_cancelled(task_record.task_id)

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            temp_path = f.name

        try:
            with pytest.raises(TranscriptCancelled):
                generate_raw_segments(
                    temp_path,
                    media_id=media_details.id,
                    task_id=task_record.task_id,
                )
            # Top-of-function check must fire before the WhisperModel is constructed.
            mock_whisper.assert_not_called()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestCreateTranscriptBlocksTaskCancellation:
    """Tests for the job body's translation of TranscriptCancelled → JobCancelled."""

    def test_body_translates_cancelled_to_job_cancelled_and_skips_embeddings(
        self, clean_database, task_record, media_details
    ):
        """When create_transcript_blocks raises TranscriptCancelled, the job body
        must raise JobCancelled (the wrapper's signal to run cancel cleanup) and
        must NOT call add_embeddings, which would otherwise clobber the
        cancelled state."""
        from orchestrator import JobCancelled, JobContext
        from tasks.transcription import run_transcript_job

        md_dict = {
            'id': media_details.id,
            'url': media_details.url,
            'media_type': media_details.media_type.value,
            'channel': media_details.channel,
            'title': media_details.title,
            'status': media_details.status.value,
        }

        with (
            patch('tasks.transcription.create_transcript_blocks') as mock_create,
            patch('tasks.transcription.add_embeddings') as mock_add,
            patch('tasks.transcription.load_embedding_model') as mock_load,
        ):
            mock_create.side_effect = TranscriptCancelled('cancelled by user')

            ctx = JobContext('cancel-mid-generation')
            with pytest.raises(JobCancelled):
                run_transcript_job(ctx, md_dict)

            mock_create.assert_called_once()
            mock_add.assert_not_called()
            mock_load.assert_not_called()
            assert ctx.skip_downstream is True

    def test_body_bails_before_embeddings_when_cancelled_mid_run(
        self, clean_database, task_record, media_details
    ):
        """Edge case: create_transcript_blocks returns successfully, but the task
        was cancelled between Whisper finishing and add_embeddings starting.
        The final DB check must catch this and skip add_embeddings."""
        from models import TranscriptBlock
        from orchestrator import JobCancelled, JobContext
        from tasks.transcription import run_transcript_job

        md_dict = {
            'id': media_details.id,
            'url': media_details.url,
            'media_type': media_details.media_type.value,
            'channel': media_details.channel,
            'title': media_details.title,
            'status': media_details.status.value,
        }

        # Return a non-empty block list so we reach the pre-embeddings check
        fake_blocks = [
            TranscriptBlock(
                text='test block',
                start_time=0,
                end_time=10,
                media_details_id=media_details.id,
                transcript_model='test',
            )
        ]

        def create_then_cancel(*args, **kwargs):
            # Simulate the user cancelling after Whisper finishes but before embeddings
            _set_cancelled(task_record.task_id)
            return fake_blocks

        with (
            patch('tasks.transcription.create_transcript_blocks') as mock_create,
            patch('tasks.transcription.add_embeddings') as mock_add,
            patch('tasks.transcription.load_embedding_model'),
        ):
            mock_create.side_effect = create_then_cancel

            ctx = JobContext(task_record.task_id)
            with pytest.raises(JobCancelled):
                run_transcript_job(ctx, md_dict)

            mock_create.assert_called_once()
            # Embeddings must not have been persisted.
            mock_add.assert_not_called()
