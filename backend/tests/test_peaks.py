"""Tests for waveform peak binning in routers.media.

`_bin_peaks` is covered by pure unit tests — no database, no ffmpeg. The endpoint
test at the bottom is the one exception and needs real ffmpeg/ffprobe binaries.
"""

import os
import shutil
import sys

import numpy as np
import pytest

# Add app to path so we can import routers.media directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from routers.media import _bin_peaks

requires_ffmpeg = pytest.mark.skipif(
    shutil.which('ffmpeg') is None, reason='needs real ffmpeg/ffprobe binaries'
)


def _pcm(samples) -> bytes:
    """Encode a list of floats as little-endian float32 PCM bytes."""
    return np.array(samples, dtype='<f4').tobytes()


def test_bins_by_max_absolute_value():
    # 8 samples → 4 bins of 2. Each bin's peak is its max absolute value.
    pcm = _pcm([0.1, -0.5, 0.2, 0.3, -0.9, 0.4, 0.05, -0.05])
    peaks = _bin_peaks(pcm, 4)
    assert peaks == pytest.approx([0.5, 0.3, 0.9, 0.05])


def test_length_always_equals_num_peaks():
    pcm = _pcm([0.1, -0.5, 0.2, 0.3, -0.9, 0.4, 0.05, -0.05])
    assert len(_bin_peaks(pcm, 8000)) == 8000


def test_short_audio_pads_with_zeros():
    # Fewer samples than requested peaks → real values then zero padding.
    pcm = _pcm([0.2, -0.4, 0.1])
    peaks = _bin_peaks(pcm, 8)
    assert peaks[:3] == pytest.approx([0.2, 0.4, 0.1])
    assert peaks[3:] == [0.0] * 5
    assert len(peaks) == 8


def test_empty_pcm_returns_empty_list():
    assert _bin_peaks(b'', 8000) == []


def test_values_rounded_to_four_decimals():
    pcm = _pcm([0.123456, -0.987654])
    peaks = _bin_peaks(pcm, 2)
    assert peaks == pytest.approx([0.1235, 0.9877], abs=1e-9)


@requires_ffmpeg
def test_peaks_endpoint_generates_and_caches(authenticated_client, tmp_path):
    """End-to-end: ffprobe + ffmpeg + numpy binning, then cache reuse."""
    import subprocess

    from database import db
    from models import MediaAccess, MediaDetails, MediaType

    client = authenticated_client

    # A real 2-second tone so ffprobe/ffmpeg have something to decode.
    audio_file = tmp_path / 'sample.wav'
    subprocess.run(
        [
            'ffmpeg',
            '-f',
            'lavfi',
            '-i',
            'sine=frequency=440:duration=2',
            '-ac',
            '1',
            '-y',
            str(audio_file),
        ],
        check=True,
        capture_output=True,
    )

    admin = next(u for u in client.get('/auth/users').json() if u['username'] == 'testadmin')
    admin_id = admin['id']

    # Explicit high id to avoid colliding with the seeded rows' serial sequence.
    media_id = 9999
    session = db.get_sync_session()
    try:
        session.add(
            MediaDetails(
                id=media_id,
                url='https://example.com/peaks-sample',
                media_type=MediaType.AUDIO,
                title='peaks-sample',
                file_path=str(audio_file),
                owner_id=admin_id,
            )
        )
        session.commit()  # commit parent first (FK not declared on the model)
        session.add(MediaAccess(user_id=admin_id, media_details_id=media_id))
        session.commit()
    finally:
        session.close()

    resp = client.get(f'/media/{media_id}/peaks', params={'num_peaks': 500})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data['peaks']) == 500
    assert data['duration'] == pytest.approx(2.0, abs=0.2)

    # A .peaks.json.gz sidecar is written and reused on the next request.
    cache_file = os.path.splitext(str(audio_file))[0] + '.peaks.json.gz'
    assert os.path.exists(cache_file)
    resp2 = client.get(f'/media/{media_id}/peaks', params={'num_peaks': 500})
    assert resp2.status_code == 200
    assert resp2.json()['peaks'] == data['peaks']
