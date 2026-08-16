"""Tests for create_transcript_blocks helper extractions."""

from unittest.mock import MagicMock, patch

from models import TranscriptBlock


class TestTryExternalSubtitles:
    """Tests for _try_external_subtitles helper."""

    @patch('services.transcript.find_subtitle_file', return_value=None)
    def test_returns_none_when_no_subtitle_file(self, mock_find):
        from services.transcript import _try_external_subtitles

        result = _try_external_subtitles('/media/video.mp4', 1, None, False, False)
        assert result is None

    @patch('services.transcript.parse_subtitle_file', return_value=[])
    @patch('services.transcript.find_subtitle_file', return_value='/media/video.en.json3')
    def test_returns_none_when_subtitle_parse_empty(self, mock_find, mock_parse):
        from services.transcript import _try_external_subtitles

        result = _try_external_subtitles('/media/video.mp4', 1, None, False, False)
        assert result is None

    @patch('services.transcript._aggregate_segments_into_blocks')
    @patch('services.transcript.parse_subtitle_file', return_value=[(0.0, 5.0, 'Hello')])
    @patch('services.transcript.find_subtitle_file', return_value='/media/video.en.json3')
    def test_returns_blocks_from_json3_subtitles(self, mock_find, mock_parse, mock_agg):
        from services.transcript import _try_external_subtitles

        mock_block = MagicMock(spec=TranscriptBlock)
        mock_agg.return_value = [mock_block]

        result = _try_external_subtitles('/media/video.mp4', 1, None, False, False)
        assert result == [mock_block]
        mock_agg.assert_called_once_with(
            [(0.0, 5.0, 'Hello')], 1, transcript_model='yt-dlp-subtitles-json3'
        )

    @patch('services.transcript._aggregate_segments_into_blocks')
    @patch('services.transcript.parse_subtitle_file', return_value=[(0.0, 5.0, 'Hello')])
    @patch('services.transcript.find_subtitle_file', return_value='/media/video.en.vtt')
    def test_returns_blocks_with_vtt_model_name(self, mock_find, mock_parse, mock_agg):
        from services.transcript import _try_external_subtitles

        mock_agg.return_value = [MagicMock(spec=TranscriptBlock)]

        _try_external_subtitles('/media/video.mp4', 1, None, False, False)
        mock_agg.assert_called_once_with(
            [(0.0, 5.0, 'Hello')], 1, transcript_model='yt-dlp-subtitles-vtt'
        )

    def test_skipped_when_force_whisper(self):
        from services.transcript import _try_external_subtitles

        result = _try_external_subtitles('/media/video.mp4', 1, None, True, False)
        assert result is None

    def test_skipped_when_force_recompute(self):
        from services.transcript import _try_external_subtitles

        result = _try_external_subtitles('/media/video.mp4', 1, None, False, True)
        assert result is None

    @patch('services.transcript.update_progress')
    @patch('services.transcript._aggregate_segments_into_blocks', return_value=[MagicMock()])
    @patch('services.transcript.parse_subtitle_file', return_value=[(0.0, 5.0, 'Hello')])
    @patch('services.transcript.find_subtitle_file', return_value='/media/video.en.json3')
    def test_updates_progress_when_task_id_present(
        self, mock_find, mock_parse, mock_agg, mock_progress
    ):
        from services.transcript import _try_external_subtitles

        _try_external_subtitles('/media/video.mp4', 42, 'task-123', False, False, user_id=7)
        mock_progress.assert_called_once_with(
            'task-123', 42, 100.0, 'Transcript from external subtitles', user_id=7
        )

    @patch('services.transcript.update_progress')
    @patch('services.transcript._aggregate_segments_into_blocks', return_value=[MagicMock()])
    @patch('services.transcript.parse_subtitle_file', return_value=[(0.0, 5.0, 'Hello')])
    @patch('services.transcript.find_subtitle_file', return_value='/media/video.en.json3')
    def test_no_progress_update_without_task_id(
        self, mock_find, mock_parse, mock_agg, mock_progress
    ):
        from services.transcript import _try_external_subtitles

        _try_external_subtitles('/media/video.mp4', 42, None, False, False)
        mock_progress.assert_not_called()


class TestTryCachedWhisper:
    """Tests for _try_cached_whisper helper."""

    @patch('services.transcript._load_whisper_cache', return_value=None)
    def test_returns_none_when_no_cache(self, mock_cache):
        from services.transcript import _try_cached_whisper

        result = _try_cached_whisper('/media/video.mp4', 1, None, 'tiny.en', False)
        assert result is None
        mock_cache.assert_called_once_with('/media/video.mp4', 'tiny.en')

    @patch('services.transcript._load_whisper_cache')
    def test_returns_none_when_force_recompute(self, mock_cache):
        from services.transcript import _try_cached_whisper

        result = _try_cached_whisper('/media/video.mp4', 1, None, 'tiny.en', True)
        assert result is None
        mock_cache.assert_not_called()

    @patch('services.transcript._aggregate_segments_into_blocks')
    @patch('services.transcript._load_whisper_cache', return_value=[(0.0, 5.0, 'Cached text')])
    def test_returns_blocks_from_cache(self, mock_cache, mock_agg):
        from services.transcript import _try_cached_whisper

        mock_block = MagicMock(spec=TranscriptBlock)
        mock_agg.return_value = [mock_block]

        result = _try_cached_whisper('/media/video.mp4', 1, None, 'tiny.en', False)
        assert result == [mock_block]
        mock_agg.assert_called_once_with([(0.0, 5.0, 'Cached text')], 1)

    @patch('services.transcript.update_progress')
    @patch('services.transcript._aggregate_segments_into_blocks', return_value=[MagicMock()])
    @patch('services.transcript._load_whisper_cache', return_value=[(0.0, 5.0, 'Cached')])
    def test_updates_progress_when_task_id_present(self, mock_cache, mock_agg, mock_progress):
        from services.transcript import _try_cached_whisper

        _try_cached_whisper('/media/video.mp4', 42, 'task-456', 'tiny.en', False, user_id=7)
        mock_progress.assert_called_once_with(
            'task-456', 42, 100.0, 'Transcript from cached whisper file', user_id=7
        )

    @patch('services.transcript.update_progress')
    @patch('services.transcript._aggregate_segments_into_blocks', return_value=[MagicMock()])
    @patch('services.transcript._load_whisper_cache', return_value=[(0.0, 5.0, 'Cached')])
    def test_no_progress_update_without_task_id(self, mock_cache, mock_agg, mock_progress):
        from services.transcript import _try_cached_whisper

        _try_cached_whisper('/media/video.mp4', 42, None, 'tiny.en', False)
        mock_progress.assert_not_called()


class TestRunFreshTranscription:
    """Tests for _run_fresh_transcription helper."""

    @patch('services.transcript._save_whisper_cache')
    @patch('services.transcript._aggregate_segments_into_blocks')
    @patch('services.transcript.generate_raw_segments', return_value=[(0.0, 10.0, 'Fresh text')])
    @patch('services.transcript.extract_transcript_audio', return_value='/tmp/audio.mp3')
    @patch('os.remove')
    def test_returns_blocks_from_fresh_transcription(
        self, mock_remove, mock_extract, mock_raw, mock_agg, mock_save
    ):
        from services.transcript import _run_fresh_transcription

        mock_block = MagicMock(spec=TranscriptBlock)
        mock_agg.return_value = [mock_block]

        result = _run_fresh_transcription('/media/video.mp4', 1, 'task-789', 'tiny.en', user_id=7)
        assert result == [mock_block]
        mock_extract.assert_called_once_with('/media/video.mp4')
        mock_raw.assert_called_once_with(
            '/tmp/audio.mp3', media_id=1, task_id='task-789', user_id=7
        )
        mock_agg.assert_called_once_with([(0.0, 10.0, 'Fresh text')], 1)

    @patch('services.transcript._save_whisper_cache')
    @patch('services.transcript._aggregate_segments_into_blocks', return_value=[])
    @patch('services.transcript.generate_raw_segments', return_value=[])
    @patch('services.transcript.extract_transcript_audio', return_value='/tmp/audio.mp3')
    @patch('os.remove')
    def test_does_not_save_cache_when_no_segments(
        self, mock_remove, mock_extract, mock_raw, mock_agg, mock_save
    ):
        from services.transcript import _run_fresh_transcription

        _run_fresh_transcription('/media/video.mp4', 1, None, 'tiny.en')
        mock_save.assert_not_called()

    @patch('services.transcript._save_whisper_cache')
    @patch('services.transcript._aggregate_segments_into_blocks', return_value=[MagicMock()])
    @patch('services.transcript.generate_raw_segments', return_value=[(0.0, 10.0, 'Text')])
    @patch('services.transcript.extract_transcript_audio', return_value='/tmp/audio.mp3')
    @patch('os.remove')
    def test_saves_cache_when_segments_produced(
        self, mock_remove, mock_extract, mock_raw, mock_agg, mock_save
    ):
        from services.transcript import _run_fresh_transcription

        _run_fresh_transcription('/media/video.mp4', 1, None, 'tiny.en')
        mock_save.assert_called_once_with('/media/video.mp4', [(0.0, 10.0, 'Text')], 'tiny.en')

    @patch('services.transcript._save_whisper_cache')
    @patch('services.transcript._aggregate_segments_into_blocks', return_value=[MagicMock()])
    @patch('services.transcript.generate_raw_segments', return_value=[(0.0, 10.0, 'Text')])
    @patch('services.transcript.extract_transcript_audio', return_value='/tmp/audio.mp3')
    @patch('os.remove')
    def test_cleans_up_audio_on_success(
        self, mock_remove, mock_extract, mock_raw, mock_agg, mock_save
    ):
        from services.transcript import _run_fresh_transcription

        _run_fresh_transcription('/media/video.mp4', 1, None, 'tiny.en')
        mock_remove.assert_called_once_with('/tmp/audio.mp3')

    @patch('services.transcript._save_whisper_cache')
    @patch('services.transcript._aggregate_segments_into_blocks', return_value=[])
    @patch('services.transcript.generate_raw_segments', side_effect=Exception('Whisper failed'))
    @patch('services.transcript.extract_transcript_audio', return_value='/tmp/audio.mp3')
    @patch('os.remove')
    def test_cleans_up_audio_on_error(
        self, mock_remove, mock_extract, mock_raw, mock_agg, mock_save
    ):
        import pytest

        from services.transcript import _run_fresh_transcription

        with pytest.raises(Exception, match='Whisper failed'):
            _run_fresh_transcription('/media/video.mp4', 1, None, 'tiny.en')

        # Audio file should still be cleaned up via finally block
        mock_remove.assert_called_once_with('/tmp/audio.mp3')


class TestCreateTranscriptBlocksOrchestrator:
    """Tests for the slimmed-down orchestrator."""

    @patch('services.transcript._run_fresh_transcription', return_value=[])
    @patch('services.transcript._try_cached_whisper', return_value=None)
    @patch('services.transcript._try_external_subtitles', return_value=None)
    @patch('services.transcript.settings_repo.sync_get_settings')
    def test_owner_id_reaches_every_transcript_path(
        self, mock_settings, mock_subs, mock_cache, mock_fresh
    ):
        """Progress events carrying no user_id are dropped by the SSE stream, so a
        transcript that loses owner_id here shows no progress to its own owner.
        """
        from services.transcript import create_transcript_blocks

        mock_settings.return_value = MagicMock(force_whisper_transcription=False)

        md = MagicMock()
        md.id = 1
        md.file_path = '/media/video.mp4'
        md.owner_id = 7

        create_transcript_blocks(md)

        for mock in (mock_subs, mock_cache, mock_fresh):
            assert mock.call_args.kwargs['user_id'] == 7

    @patch('services.transcript._run_fresh_transcription')
    @patch('services.transcript._try_cached_whisper')
    @patch('services.transcript._try_external_subtitles')
    @patch('services.transcript.settings_repo.sync_get_settings')
    def test_returns_subtitles_when_available(
        self, mock_settings, mock_subs, mock_cache, mock_fresh
    ):
        from services.transcript import create_transcript_blocks

        mock_settings.return_value = MagicMock(force_whisper_transcription=False)
        mock_subs.return_value = [MagicMock(spec=TranscriptBlock)]

        md = MagicMock()
        md.id = 1
        md.file_path = '/media/video.mp4'

        result = create_transcript_blocks(md)
        assert result == mock_subs.return_value
        mock_cache.assert_not_called()
        mock_fresh.assert_not_called()

    @patch('services.transcript._run_fresh_transcription')
    @patch('services.transcript._try_cached_whisper')
    @patch('services.transcript._try_external_subtitles', return_value=None)
    @patch('services.transcript.settings_repo.sync_get_settings')
    def test_falls_through_to_cache(self, mock_settings, mock_subs, mock_cache, mock_fresh):
        from services.transcript import create_transcript_blocks

        mock_settings.return_value = MagicMock(force_whisper_transcription=False)
        mock_cache.return_value = [MagicMock(spec=TranscriptBlock)]

        md = MagicMock()
        md.id = 1
        md.file_path = '/media/video.mp4'

        result = create_transcript_blocks(md)
        assert result == mock_cache.return_value
        mock_fresh.assert_not_called()

    @patch('services.transcript._run_fresh_transcription')
    @patch('services.transcript._try_cached_whisper', return_value=None)
    @patch('services.transcript._try_external_subtitles', return_value=None)
    @patch('services.transcript.settings_repo.sync_get_settings')
    def test_falls_through_to_fresh_transcription(
        self, mock_settings, mock_subs, mock_cache, mock_fresh
    ):
        from services.transcript import create_transcript_blocks

        mock_settings.return_value = MagicMock(force_whisper_transcription=False)
        mock_fresh.return_value = [MagicMock(spec=TranscriptBlock)]

        md = MagicMock()
        md.id = 1
        md.file_path = '/media/video.mp4'

        result = create_transcript_blocks(md)
        assert result == mock_fresh.return_value

    @patch(
        'services.transcript._get_whisper_cache_path', return_value='/media/video.whisper.json.gz'
    )
    @patch('services.transcript._run_fresh_transcription', return_value=[])
    @patch('services.transcript._try_cached_whisper', return_value=None)
    @patch('services.transcript._try_external_subtitles', return_value=None)
    @patch('services.transcript.settings_repo.sync_get_settings')
    @patch('os.path.exists', return_value=True)
    @patch('os.remove')
    def test_force_recompute_deletes_cache_file(
        self, mock_remove, mock_exists, mock_settings, mock_subs, mock_cache, mock_fresh, mock_path
    ):
        from services.transcript import create_transcript_blocks

        mock_settings.return_value = MagicMock(force_whisper_transcription=False)

        md = MagicMock()
        md.id = 1
        md.file_path = '/media/video.mp4'

        create_transcript_blocks(md, force_recompute=True)
        mock_remove.assert_called_once_with('/media/video.whisper.json.gz')
