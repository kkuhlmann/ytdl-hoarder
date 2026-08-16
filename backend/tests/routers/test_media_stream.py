"""Regression tests for the media/clip streaming handlers."""

from database import db
from models import MediaDetails, MediaType


def _set_media_file(media_id: int, file_path, media_type: MediaType) -> None:
    session = db.get_sync_session()
    try:
        md = session.get(MediaDetails, media_id)
        md.file_path = str(file_path)
        md.media_type = media_type
        session.add(md)
        session.commit()
    finally:
        session.close()


def test_stream_mkv_video_forces_mp4_content_type(authenticated_client, tmp_path):
    # .mkv guesses video/x-matroska; VIDEO media must force video/mp4 (mirrors
    # the clip handler's behavior). Fails while is_video compares against 'video'.
    f = tmp_path / 'movie.mkv'
    f.write_bytes(b'\x00' * 2048)
    _set_media_file(1, f, MediaType.VIDEO)

    resp = authenticated_client.get('/media/1')
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'video/mp4'


def test_stream_audio_keeps_guessed_content_type(authenticated_client, tmp_path):
    f = tmp_path / 'song.mp3'
    f.write_bytes(b'\x00' * 2048)
    _set_media_file(1, f, MediaType.AUDIO)

    resp = authenticated_client.get('/media/1')
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'audio/mpeg'


def test_stream_range_request_returns_206(authenticated_client, tmp_path):
    f = tmp_path / 'movie.mp4'
    f.write_bytes(b'\x00' * 2048)
    _set_media_file(1, f, MediaType.VIDEO)

    resp = authenticated_client.get('/media/1', headers={'range': 'bytes=0-1023'})
    assert resp.status_code == 206
    assert resp.headers['content-range'] == 'bytes 0-1023/2048'
    assert resp.headers['content-length'] == '1024'


def test_stream_missing_file_returns_404(authenticated_client, tmp_path):
    _set_media_file(1, tmp_path / 'gone.mp4', MediaType.VIDEO)

    resp = authenticated_client.get('/media/1')
    assert resp.status_code == 404
