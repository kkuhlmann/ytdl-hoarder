"""Unit tests for file naming and organization utilities.

Pure unit tests — no database, no network, no yt-dlp calls.
Tests get_url_hash, sanitize_folder_name, and clean_outtmpl with url_hash support.
"""

from utils import sanitize_folder_name
from ytdlp.options import clean_outtmpl
from ytdlp.urls import get_url_hash

# --- get_url_hash ---


class TestGetUrlHash:
    def test_returns_11_char_hex_string(self):
        result = get_url_hash('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        assert len(result) == 11
        assert all(c in '0123456789abcdef' for c in result)

    def test_deterministic(self):
        url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        assert get_url_hash(url) == get_url_hash(url)

    def test_different_urls_produce_different_hashes(self):
        hash1 = get_url_hash('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        hash2 = get_url_hash('https://www.youtube.com/watch?v=lYBUbBu4W08')
        assert hash1 != hash2

    def test_empty_url(self):
        result = get_url_hash('')
        assert len(result) == 11


# --- sanitize_folder_name ---


class TestSanitizeFolderName:
    def test_normal_name_passes_through(self):
        assert sanitize_folder_name('My Channel') == 'My Channel'

    def test_removes_slashes(self):
        assert sanitize_folder_name('A/B\\C') == 'ABC'

    def test_removes_colons_and_special_chars(self):
        assert sanitize_folder_name('Channel: The Best*?') == 'Channel The Best'

    def test_removes_angle_brackets_and_pipes(self):
        assert sanitize_folder_name('Name<>|test') == 'Nametest'

    def test_strips_leading_trailing_dots_and_spaces(self):
        assert sanitize_folder_name('...My Channel...') == 'My Channel'
        assert sanitize_folder_name('  My Channel  ') == 'My Channel'

    def test_empty_string_returns_unknown(self):
        assert sanitize_folder_name('') == 'Unknown'

    def test_only_unsafe_chars_returns_unknown(self):
        assert sanitize_folder_name('/:*?"<>|') == 'Unknown'

    def test_truncates_to_100_chars(self):
        long_name = 'A' * 150
        result = sanitize_folder_name(long_name)
        assert len(result) == 100
        assert result == 'A' * 100

    def test_preserves_unicode(self):
        assert sanitize_folder_name('Linus Tech Tipps') == 'Linus Tech Tipps'

    def test_null_byte_removed(self):
        assert sanitize_folder_name('test\x00name') == 'testname'


# --- clean_outtmpl with url_hash ---


class TestCleanOuttmplWithUrlHash:
    def test_regular_format_with_hash(self):
        result = clean_outtmpl(
            title='My Video',
            save_path='/mnt/video/channel',
            url_hash='abc12345678',
        )
        assert result == '/mnt/video/channel/My Video [abc12345678].%(ext)s'

    def test_playlist_format_with_hash(self):
        result = clean_outtmpl(
            title='Playlist Video',
            save_path='/mnt/audio/playlist',
            is_playlist=True,
            playlist_index=3,
            url_hash='def99887766',
        )
        assert result == '/mnt/audio/playlist/03 - Playlist Video [def99887766].%(ext)s'

    def test_none_url_hash_omits_brackets(self):
        result = clean_outtmpl(
            title='My Video',
            save_path='/mnt/video',
            url_hash=None,
        )
        assert result == '/mnt/video/My Video.%(ext)s'

    def test_default_url_hash_is_none(self):
        """Backward compatibility: omitting url_hash produces the old format."""
        result = clean_outtmpl(title='My Video', save_path='/mnt/video')
        assert result == '/mnt/video/My Video.%(ext)s'

    def test_title_with_slashes_cleaned(self):
        result = clean_outtmpl(
            title='Video / With / Slashes',
            save_path='/mnt/video',
            url_hash='abc12345678',
        )
        # Slashes are removed by the printable filter
        assert '/' not in result.replace('/mnt/video/', '')
        assert '[abc12345678]' in result

    def test_playlist_index_zero(self):
        result = clean_outtmpl(
            title='First Video',
            save_path='/mnt/video',
            is_playlist=True,
            playlist_index=0,
            url_hash='abc12345678',
        )
        assert result == '/mnt/video/00 - First Video [abc12345678].%(ext)s'
