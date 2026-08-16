"""cleanup_task_files glob safety: url-hash matching, literal titles, no wildcard sweeps."""

from types import SimpleNamespace

import pytest

from services.cleanup import cleanup_task_files
from ytdlp.urls import get_url_hash


@pytest.fixture
def media_dirs(tmp_path, monkeypatch):
    audio = tmp_path / 'audio'
    video = tmp_path / 'video'
    audio.mkdir()
    video.mkdir()
    monkeypatch.setattr(
        'services.cleanup.settings',
        SimpleNamespace(storage=SimpleNamespace(audio_path=str(audio), video_path=str(video))),
    )
    return audio, video


def test_url_hash_matches_only_own_partials(media_dirs):
    _, video = media_dirs
    url = 'https://www.youtube.com/watch?v=abc123'
    url_hash = get_url_hash(url)
    own_part = video / f'My Video [{url_hash}].webm.part'
    own_ytdl = video / f'My Video [{url_hash}].webm.ytdl'
    other = video / 'Other Video [00000000000].webm.part'
    for f in (own_part, own_ytdl, other):
        f.write_bytes(b'x')

    deleted = cleanup_task_files(task_title='My Video', task_url=url)

    assert deleted == 2
    assert not own_part.exists()
    assert not own_ytdl.exists()
    assert other.exists()


def test_bracketed_title_partial_is_matched(media_dirs):
    # Title-only fallback: bracketed titles must match literally (fnmatch has no
    # backslash escape, so the old hand-rolled escaping never matched these).
    _, video = media_dirs
    part = video / 'Song [Official Video] [abc12345678].webm.part'
    part.write_bytes(b'x')

    deleted = cleanup_task_files(task_title='Song [Official Video]')

    assert deleted == 1
    assert not part.exists()


def test_wildcard_title_does_not_sweep_unrelated_partials(media_dirs):
    # A task titled '*' (e.g. a raw junk URL submitted as a download) must not
    # glob every in-flight partial in the library.
    audio, video = media_dirs
    unrelated = [
        video / 'Unrelated A [11111111111].webm.part',
        audio / 'Unrelated B [22222222222].m4a.ytdl',
    ]
    for f in unrelated:
        f.write_bytes(b'x')

    deleted = cleanup_task_files(task_title='*')

    assert deleted == 0
    assert all(f.exists() for f in unrelated)


def test_no_title_or_url_is_a_noop(media_dirs):
    assert cleanup_task_files() == 0
