"""The download paths that finish successfully without downloading anything.

ctx.skip_downstream only suppresses the in-memory enqueue — it writes nothing to
the DB. Without an explicit terminal write these paths leave the chained transcript
sitting QUEUED forever with nothing behind it.
"""

from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.utils import DownloadError

from database import db
from models import (
    AudioQuality,
    DownloadQuality,
    MediaDetails,
    MediaType,
    TaskRecord,
    TaskStatus,
    TaskType,
)
from orchestrator import JobContext
from repositories import task_records
from schemas import DownloadJobDTO, MediaDetailsDTO
from tasks.downloads import _download_with_fallback

URL = 'https://www.youtube.com/watch?v=skipPath01'
DOWNLOAD_TASK_ID = 'skip-path-download'


@pytest.fixture
def chain(test_database):
    """A download with both downstream rows, as populate time creates them."""
    session = db.get_sync_session()
    try:
        session.add(MediaDetails(url=URL, media_type=MediaType.VIDEO, title='T'))
        session.commit()
    finally:
        session.close()

    for task_id, task_type in (
        (f'{DOWNLOAD_TASK_ID}-tr', TaskType.TRANSCRIPT_GENERATION),
        (f'{DOWNLOAD_TASK_ID}-spr', TaskType.SPRITE_GENERATION),
    ):
        task_records.sync_insert_task(
            TaskRecord(
                task_id=task_id,
                task_type=task_type,
                status=TaskStatus.QUEUED,
                upstream_task_ids=[DOWNLOAD_TASK_ID],
                download_job_url=URL,
                media_type=MediaType.VIDEO,
            )
        )


def _dto() -> DownloadJobDTO:
    md = MediaDetailsDTO(id=1, url=URL, media_type=MediaType.VIDEO, title='T')
    return DownloadJobDTO(
        url=URL, media_type=MediaType.VIDEO, media_details=md, generate_transcript=True
    )


def _statuses() -> dict[str, TaskStatus]:
    return {
        suffix: task_records.sync_get_task_by_task_id(f'{DOWNLOAD_TASK_ID}-{suffix}').status
        for suffix in ('tr', 'spr')
    }


def test_repeat_download_skips_the_transcript_only(chain):
    from tasks.downloads import run_download_job

    ctx = JobContext(task_id=DOWNLOAD_TASK_ID, user_id=1)
    with (
        patch('tasks.downloads._check_repeat_download', return_value=True),
        patch('tasks.downloads._determine_download_subdirectory', return_value=('', False)),
    ):
        run_download_job(ctx, _dto().model_dump(mode='json'))

    statuses = _statuses()
    assert statuses['tr'] == TaskStatus.SKIPPED, 'transcript must not be left stranded QUEUED'
    # The sprite is dispatched by DownloadHooks.on_success — the body must not
    # terminate it on its way past.
    assert statuses['spr'] == TaskStatus.QUEUED

    tr = task_records.sync_get_task_by_task_id(f'{DOWNLOAD_TASK_ID}-tr')
    assert tr.status_message == 'Skipped - media was already downloaded'


def test_existing_file_skips_the_transcript_only(chain):
    from tasks.downloads import run_download_job

    ctx = JobContext(task_id=DOWNLOAD_TASK_ID, user_id=1)
    with (
        patch('tasks.downloads._check_repeat_download', return_value=False),
        patch('tasks.downloads._determine_download_subdirectory', return_value=('', False)),
        patch('tasks.downloads._build_download_options', return_value={'outtmpl': 'x'}),
        patch('tasks.downloads._check_file_exists_on_disk', return_value=('/tmp/x.mp4', True)),
        patch('tasks.downloads._handle_file_already_exists', return_value={'id': 1}),
    ):
        run_download_job(ctx, _dto().model_dump(mode='json'))

    statuses = _statuses()
    assert statuses['tr'] == TaskStatus.SKIPPED
    assert statuses['spr'] == TaskStatus.QUEUED

    tr = task_records.sync_get_task_by_task_id(f'{DOWNLOAD_TASK_ID}-tr')
    assert tr.status_message == 'Skipped - transcript already exists'


def test_no_transcript_row_is_a_harmless_noop(test_database):
    """The marking call must not need a guard when the chain had no transcript."""
    assert task_records.sync_skip_downstream_transcripts('no-such-download', 'Skipped') == 0


# ------------------------------------------------------- format-fallback option rebuild
#
# The fallback builds a second options dict from scratch, so anything the primary build
# passed and this one forgets is silently downgraded for that download only.


def test_fallback_preserves_quality_audio_cap_and_cookies(monkeypatch):
    captured = {}

    def fake_create_ydl_options(dto, **kwargs):
        captured.update(kwargs)
        return {'format': 'best', 'save_path': '/tmp'}

    monkeypatch.setattr('tasks.downloads.create_ydl_options', fake_create_ydl_options)
    monkeypatch.setattr('tasks.downloads.YoutubeDL', MagicMock())

    ydl = MagicMock()
    ydl.process_ie_result.side_effect = DownloadError('Requested format is not available')

    dto = DownloadJobDTO(
        url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        audio_only=True,
        download_quality=DownloadQuality.Q720P,
        audio_quality=AudioQuality.K64,
    )

    _download_with_fallback(
        ydl,
        {'outtmpl': '/tmp/out.%(ext)s'},
        dto,
        None,
        {},
        '',
        lambda _d: None,
        lambda _d: None,
        cookie_file='/tmp/copy.txt',
    )

    assert captured['quality'] == '720'
    assert captured['audio_abr_cap'] == 64
    assert captured['cookie_file'] == '/tmp/copy.txt'
    assert captured['use_fallback_format'] is True
