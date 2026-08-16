"""Unit tests for subtitle_parser module.

Pure unit tests — no database, no testcontainers. These run fast.
"""

import json
import os

# Add app to path so we can import subtitle_parser directly
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from ytdlp.subtitles import (
    find_subtitle_file,
    parse_json3_subtitles,
    parse_subtitle_file,
    parse_vtt_subtitles,
)

# --- JSON3 parsing tests ---


def test_parse_json3_basic():
    """Well-formed JSON3 produces correct segments with ms-to-seconds conversion."""
    data = {
        'events': [
            {
                'tStartMs': 1000,
                'dDurationMs': 2000,
                'segs': [{'utf8': 'Hello '}, {'utf8': 'world'}],
            },
            {
                'tStartMs': 5000,
                'dDurationMs': 3000,
                'segs': [{'utf8': 'Second segment'}],
            },
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json3', delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        segments = parse_json3_subtitles(path)
        assert len(segments) == 2
        assert segments[0] == (1.0, 3.0, 'Hello world')
        assert segments[1] == (5.0, 8.0, 'Second segment')
    finally:
        os.unlink(path)


def test_parse_json3_skips_metadata_events():
    """Events without 'segs' key (metadata/styling) are skipped."""
    data = {
        'events': [
            # Metadata event (window positioning) — no segs
            {'tStartMs': 0, 'dDurationMs': 0},
            # Real subtitle event
            {
                'tStartMs': 1000,
                'dDurationMs': 2000,
                'segs': [{'utf8': 'Actual text'}],
            },
            # Another metadata event
            {'tStartMs': 3000},
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json3', delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        segments = parse_json3_subtitles(path)
        assert len(segments) == 1
        assert segments[0] == (1.0, 3.0, 'Actual text')
    finally:
        os.unlink(path)


def test_parse_json3_empty_text():
    """Events with only whitespace text are filtered out."""
    data = {
        'events': [
            {
                'tStartMs': 0,
                'dDurationMs': 1000,
                'segs': [{'utf8': '   '}, {'utf8': '\n'}],
            },
            {
                'tStartMs': 1000,
                'dDurationMs': 1000,
                'segs': [{'utf8': 'Real text'}],
            },
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json3', delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        segments = parse_json3_subtitles(path)
        assert len(segments) == 1
        assert segments[0][2] == 'Real text'
    finally:
        os.unlink(path)


def test_parse_json3_empty_events():
    """Empty events list returns empty segments."""
    data = {'events': []}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json3', delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        segments = parse_json3_subtitles(path)
        assert segments == []
    finally:
        os.unlink(path)


# --- VTT parsing tests ---


def test_parse_vtt_basic():
    """Well-formed VTT produces correct segments."""
    vtt_content = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:06.500 --> 00:00:10.000
Second subtitle line
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.vtt', delete=False) as f:
        f.write(vtt_content)
        path = f.name

    try:
        segments = parse_vtt_subtitles(path)
        assert len(segments) == 2
        assert segments[0] == (1.0, 5.0, 'Hello world')
        assert segments[1] == (6.5, 10.0, 'Second subtitle line')
    finally:
        os.unlink(path)


def test_parse_vtt_strips_tags():
    """VTT formatting tags are removed from text."""
    vtt_content = """WEBVTT

00:00:01.000 --> 00:00:05.000
<c>Hello</c> <b>world</b>

00:00:06.000 --> 00:00:08.000
<c.colorE5E5E5>styled text</c>
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.vtt', delete=False) as f:
        f.write(vtt_content)
        path = f.name

    try:
        segments = parse_vtt_subtitles(path)
        assert len(segments) == 2
        assert segments[0] == (1.0, 5.0, 'Hello world')
        assert segments[1] == (6.0, 8.0, 'styled text')
    finally:
        os.unlink(path)


def test_parse_vtt_multiline():
    """VTT with multi-line subtitle cues are joined."""
    vtt_content = """WEBVTT

00:00:01.000 --> 00:00:05.000
First line
Second line
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.vtt', delete=False) as f:
        f.write(vtt_content)
        path = f.name

    try:
        segments = parse_vtt_subtitles(path)
        assert len(segments) == 1
        assert segments[0] == (1.0, 5.0, 'First line Second line')
    finally:
        os.unlink(path)


# --- find_subtitle_file tests ---


def test_find_subtitle_file_json3_preferred():
    """JSON3 is preferred over VTT when both exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = os.path.join(tmpdir, 'video')
        media_path = base + '.mp4'
        json3_path = base + '.en.json3'
        vtt_path = base + '.en.vtt'

        # Create both files
        for path in [media_path, json3_path, vtt_path]:
            with open(path, 'w') as f:
                f.write('')

        result = find_subtitle_file(media_path)
        assert result == json3_path


def test_find_subtitle_file_vtt_fallback():
    """VTT is used when JSON3 doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = os.path.join(tmpdir, 'video')
        media_path = base + '.mp4'
        vtt_path = base + '.en.vtt'

        for path in [media_path, vtt_path]:
            with open(path, 'w') as f:
                f.write('')

        result = find_subtitle_file(media_path)
        assert result == vtt_path


def test_find_subtitle_file_returns_none():
    """Returns None when no subtitle files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        media_path = os.path.join(tmpdir, 'video.mp4')
        with open(media_path, 'w') as f:
            f.write('')

        result = find_subtitle_file(media_path)
        assert result is None


# --- parse_subtitle_file dispatcher tests ---


def test_parse_subtitle_file_dispatches_json3():
    """Dispatcher calls JSON3 parser for .json3 files."""
    data = {
        'events': [
            {'tStartMs': 0, 'dDurationMs': 1000, 'segs': [{'utf8': 'test'}]},
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json3', delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        segments = parse_subtitle_file(path)
        assert len(segments) == 1
        assert segments[0][2] == 'test'
    finally:
        os.unlink(path)


def test_parse_subtitle_file_dispatches_vtt():
    """Dispatcher calls VTT parser for .vtt files."""
    vtt_content = """WEBVTT

00:00:00.000 --> 00:00:01.000
test
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.vtt', delete=False) as f:
        f.write(vtt_content)
        path = f.name

    try:
        segments = parse_subtitle_file(path)
        assert len(segments) == 1
        assert segments[0][2] == 'test'
    finally:
        os.unlink(path)


def test_parse_subtitle_file_handles_errors():
    """Corrupt file returns empty list instead of raising."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json3', delete=False) as f:
        f.write('this is not valid json{{{')
        path = f.name

    try:
        segments = parse_subtitle_file(path)
        assert segments == []
    finally:
        os.unlink(path)


def test_parse_subtitle_file_unsupported_format():
    """Unsupported file extension returns empty list."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
        f.write('1\n00:00:01,000 --> 00:00:02,000\ntest\n')
        path = f.name

    try:
        segments = parse_subtitle_file(path)
        assert segments == []
    finally:
        os.unlink(path)
