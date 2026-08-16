"""Characterization tests: every hooks class's lifecycle writes, pinned.

status_message strings render in the Tasks UI — they are API and must not
change. These tests run green before AND after the consolidation refactor.
"""

from types import SimpleNamespace
from typing import ClassVar

import pytest

import orchestrator.hooks as hooks_mod
from models import TaskStatus
from orchestrator.hooks import (
    BaseStatusHooks,
    ClipHooks,
    DownloadHooks,
    SpriteHooks,
    TranscriptHooks,
)


class _Recorder:
    def __init__(self, retval=None):
        self.calls = []
        self._retval = retval

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._retval


@pytest.fixture
def rec(monkeypatch):
    r = SimpleNamespace(
        tr_update=_Recorder(),
        tr_downstream=_Recorder(),
        md_update=_Recorder(),
        md_by_url=_Recorder(retval=None),
        # DownloadHooks.on_success re-fetches by id to dispatch sprites; retval=None
        # makes that a no-op so the download assertions stay focused.
        md_by_id=_Recorder(retval=None),
        clip_update=_Recorder(),
        publish=_Recorder(),
    )
    monkeypatch.setattr(hooks_mod.tr_repo, 'sync_update_one', r.tr_update)
    monkeypatch.setattr(hooks_mod.tr_repo, 'sync_mark_downstream_as_failed', r.tr_downstream)
    monkeypatch.setattr(hooks_mod.md_repo, 'sync_update_one', r.md_update)
    monkeypatch.setattr(
        hooks_mod.md_repo, 'sync_get_media_details_by_url_and_media_type', r.md_by_url
    )
    monkeypatch.setattr(hooks_mod.md_repo, 'sync_get_media_details_by_id', r.md_by_id)
    monkeypatch.setattr(hooks_mod.clips_repo, 'sync_update_clip', r.clip_update)
    monkeypatch.setattr(hooks_mod, 'publish_status_change', r.publish)
    return r


class _MdHooks(BaseStatusHooks):
    """Concrete BaseStatusHooks: fixed media_details_id, like real subclasses."""

    def get_media_details_id(self, args):
        return 42


class TestBaseStatusHooks:
    def test_before_start(self, rec):
        _MdHooks().before_start('t1', [], {})
        assert rec.tr_update.calls == [
            (
                (
                    't1',
                    {
                        'status': 'IN_PROGRESS',
                        'status_message': 'Processing...',
                        'error_code': None,
                    },
                ),
                {},
            )
        ]
        assert rec.md_update.calls == [((42, {'status': 'IN_PROGRESS'}), {})]
        assert rec.publish.calls == [(('t1', 'IN_PROGRESS', 'Processing...'), {'user_id': None})]

    def test_on_success(self, rec):
        _MdHooks().on_success(None, 't1', [], {})
        assert rec.tr_update.calls == [
            (
                (
                    't1',
                    {
                        'status': 'COMPLETE',
                        'status_message': 'Task completed successfully',
                        'error_code': None,
                    },
                ),
                {},
            )
        ]
        assert rec.md_update.calls == [((42, {'status': 'COMPLETE'}), {})]

    def test_on_failure_truncates_error(self, rec):
        _MdHooks().on_failure(ValueError('x' * 500), 't1', [], {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status'] == 'FAILED'
        assert args[1]['status_message'] == 'Task failed: ' + 'x' * 200

    def test_on_failure_no_exc(self, rec):
        _MdHooks().on_failure(None, 't1', [], {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Task failed: Unknown error'

    def test_on_retry(self, rec):
        _MdHooks().on_retry(ValueError('boom'), 't1', [], {})
        ((args, _),) = rec.tr_update.calls
        assert args[1] == {
            'status': 'RETRY',
            'status_message': 'Retrying due to: boom',
            'error_code': 'ValueError',
        }
        assert rec.md_update.calls == [((42, {'status': 'RETRY'}), {})]

    def test_error_code_classifies_the_failure(self, rec):
        _MdHooks().on_failure(RuntimeError('HTTP Error 403: Forbidden'), 't1', [], {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['error_code'] == 'HTTP 403'

    def test_error_code_cleared_when_a_retry_starts_running(self, rec):
        """A code from the previous attempt must not survive into the next one."""
        _MdHooks().on_retry(ValueError('boom'), 't1', [], {})
        _MdHooks().before_start('t1', [], {})
        assert rec.tr_update.calls[-1][0][1]['error_code'] is None


class TestDownloadHooks:
    ARGS: ClassVar = [
        {'url': 'https://x/v', 'media_type': 'VIDEO', 'user_id': 7, 'media_details': {'id': 9}}
    ]

    def test_before_start_message(self, rec):
        DownloadHooks().before_start('t1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Starting download...'
        assert rec.md_update.calls == [((9, {'status': 'IN_PROGRESS'}), {})]
        assert rec.publish.calls[0][1] == {'user_id': 7}

    def test_on_success_not_ready_is_untouched(self, rec):
        DownloadHooks().on_success({'status': TaskStatus.NOT_READY.value}, 't1', self.ARGS, {})
        assert rec.tr_update.calls == []
        assert rec.md_update.calls == []
        assert rec.publish.calls == []

    def test_on_success_invalid_retval_fails_without_md_write(self, rec):
        DownloadHooks().on_success(None, 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status'] == 'FAILED'
        assert args[1]['status_message'] == 'Download completed but no media details returned'
        assert rec.md_update.calls == []

    def test_on_success_happy_path(self, rec):
        DownloadHooks().on_success({'id': 9}, 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status'] == 'COMPLETE'
        assert args[1]['status_message'] == 'Download completed'
        assert args[1]['percent_complete'] == 100
        ((md_args, _),) = rec.md_update.calls
        assert md_args[0] == 9
        assert md_args[1]['status'] == 'COMPLETE'
        assert 'downloaded_at' in md_args[1]

    def test_on_failure_marks_downstream_after_status(self, rec):
        DownloadHooks().on_failure(RuntimeError('net'), 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Download failed: net'
        assert rec.tr_downstream.calls == [(('t1',), {})]


class TestTranscriptHooks:
    ARGS: ClassVar = [{'id': 5, 'title': 'T', 'channel': 'C', 'owner_id': 3}]

    def test_before_start_carries_title_channel(self, rec):
        TranscriptHooks().before_start('t1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1] == {
            'status': 'IN_PROGRESS',
            'status_message': 'Generating transcript...',
            'error_code': None,
            'title': 'T',
            'channel': 'C',
            'percent_complete': 0,
        }
        assert rec.md_update.calls == []  # MediaDetails tracked via FK, not written here

    def test_on_success(self, rec):
        TranscriptHooks().on_success(None, 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Transcript generated'
        assert args[1]['percent_complete'] == 100

    def test_on_failure_message(self, rec):
        TranscriptHooks().on_failure(RuntimeError('oom'), 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Transcript generation failed: oom'

    def test_on_retry_message(self, rec):
        TranscriptHooks().on_retry(RuntimeError('oom'), 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Retrying transcript due to: oom'


class TestClipHooks:
    ARGS: ClassVar = [{'clip_id': 11, 'user_id': 4}]

    def test_before_start(self, rec):
        ClipHooks().before_start('t1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1] == {
            'status': 'IN_PROGRESS',
            'status_message': 'Generating clip...',
            'error_code': None,
            'percent_complete': 0,
        }
        assert rec.clip_update.calls == [((11, {'status': 'IN_PROGRESS'}), {})]

    def test_on_success(self, rec):
        ClipHooks().on_success(None, 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Clip created successfully'
        assert args[1]['percent_complete'] == 100
        assert rec.clip_update.calls == [((11, {'status': 'COMPLETE'}), {})]

    def test_on_failure(self, rec):
        ClipHooks().on_failure(RuntimeError('ffmpeg'), 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Clip generation failed: ffmpeg'
        assert rec.clip_update.calls == [((11, {'status': 'FAILED'}), {})]

    def test_on_retry(self, rec):
        ClipHooks().on_retry(RuntimeError('ffmpeg'), 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Clip generation retrying: ffmpeg'


class TestSpriteHooks:
    ARGS: ClassVar = [{'media_details_id': 42, 'user_id': 4}]

    def test_before_start(self, rec):
        SpriteHooks().before_start('t1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1] == {
            'status': 'IN_PROGRESS',
            'status_message': 'Generating sprite sheet...',
            'error_code': None,
        }
        # No MediaDetails write — there is no sprite-status column to mirror into.
        assert rec.md_update.calls == []

    def test_on_success(self, rec):
        SpriteHooks().on_success(None, 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status'] == 'COMPLETE'
        assert args[1]['status_message'] == 'Sprite sheet generated'

    def test_on_failure(self, rec):
        SpriteHooks().on_failure(RuntimeError('ffmpeg'), 't1', self.ARGS, {})
        ((args, _),) = rec.tr_update.calls
        assert args[1]['status_message'] == 'Sprite generation failed: ffmpeg'

    def test_publishes_owner_user_id(self, rec):
        SpriteHooks().before_start('t1', self.ARGS, {})
        ((_, kwargs),) = rec.publish.calls
        assert kwargs['user_id'] == 4

    def test_on_cancel_deletes_partial_output(self, monkeypatch):
        deleted = []
        monkeypatch.setattr(
            'tasks.sprites.delete_partial_sprite_output', lambda mid: deleted.append(mid)
        )
        SpriteHooks().on_cancel('t1', self.ARGS)
        assert deleted == [42]


class TestDownloadHooksSpriteDispatch:
    """on_success is where sprites are dispatched — it fires for exactly the right outcomes."""

    ARGS: ClassVar = [{'url': 'https://x/y', 'media_type': 'VIDEO', 'user_id': 3}]

    def test_dispatches_for_a_real_media_row(self, rec, monkeypatch):
        submitted = []
        monkeypatch.setattr(
            'tasks.sprites.sync_submit_sprites_job',
            lambda media, **kw: submitted.append((media, kw)),
        )
        rec.md_by_id._retval = SimpleNamespace(id=7, owner_id=99)

        DownloadHooks().on_success({'id': 7}, 't1', self.ARGS, {})

        assert len(submitted) == 1
        assert submitted[0][1]['user_id'] == 99

    def test_no_dispatch_on_not_ready_retval(self, rec, monkeypatch):
        submitted = []
        monkeypatch.setattr(
            'tasks.sprites.sync_submit_sprites_job', lambda media, **kw: submitted.append(media)
        )
        DownloadHooks().on_success({'status': 'NOT_READY'}, 't1', self.ARGS, {})
        assert submitted == []

    def test_no_dispatch_on_invalid_retval(self, rec, monkeypatch):
        submitted = []
        monkeypatch.setattr(
            'tasks.sprites.sync_submit_sprites_job', lambda media, **kw: submitted.append(media)
        )
        DownloadHooks().on_success(None, 't1', self.ARGS, {})
        assert submitted == []

    def test_dispatch_runs_after_the_complete_write(self, rec, monkeypatch):
        """It's last on purpose, so a raise costs only the sheet."""
        rec.md_by_id._retval = SimpleNamespace(id=7, owner_id=99)

        def explode(media, **kw):
            msg = 'orchestrator down'
            raise RuntimeError(msg)

        monkeypatch.setattr('tasks.sprites.sync_submit_sprites_job', explode)

        with pytest.raises(RuntimeError):
            DownloadHooks().on_success({'id': 7}, 't1', self.ARGS, {})

        ((args, _),) = rec.tr_update.calls
        assert args[1]['status'] == 'COMPLETE'
        assert rec.publish.calls, 'SSE publish must already have happened'
