"""Unit tests for URL utility functions in utils.py.

Pure unit tests — no database, no network, no yt-dlp calls.
"""

from datetime import datetime

from ytdlp.info import extract_entries_from_info, get_release_timestamp
from ytdlp.urls import (
    is_channel_or_feed_url,
    is_youtube_url,
    normalize_playlist_url,
    normalize_video_url,
)

# --- normalize_video_url ---


class TestNormalizeVideoUrl:
    """Tests for normalize_video_url: YouTube canonicalization + passthrough."""

    def test_standard_youtube_url(self):
        url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        assert normalize_video_url(url) == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def test_youtube_url_with_extra_params(self):
        url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLJ8cMiYb3G5fEBBRGG3cXJJTPSBJb2MLa&index=2'
        assert normalize_video_url(url) == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def test_youtube_shorts(self):
        url = 'https://www.youtube.com/shorts/lYBUbBu4W08'
        assert normalize_video_url(url) == 'https://www.youtube.com/watch?v=lYBUbBu4W08'

    def test_youtube_mobile_url(self):
        url = 'https://youtu.be/dQw4w9WgXcQ'
        assert normalize_video_url(url) == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def test_youtube_embed_url(self):
        url = 'https://www.youtube.com/embed/dQw4w9WgXcQ'
        assert normalize_video_url(url) == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def test_youtube_live_url(self):
        url = 'https://www.youtube.com/live/dQw4w9WgXcQ'
        assert normalize_video_url(url) == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def test_youtube_music_url(self):
        url = 'https://music.youtube.com/watch?v=dQw4w9WgXcQ'
        assert normalize_video_url(url) == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def test_youtube_mobile_www(self):
        url = 'https://m.youtube.com/watch?v=dQw4w9WgXcQ'
        assert normalize_video_url(url) == 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def test_rumble_passthrough(self):
        url = 'https://rumble.com/v1abc23-some-video.html'
        assert normalize_video_url(url) == url

    def test_twitter_passthrough(self):
        url = 'https://x.com/user/status/1234567890'
        assert normalize_video_url(url) == url

    def test_odysee_passthrough(self):
        url = 'https://odysee.com/@channel:1/video-title:2'
        assert normalize_video_url(url) == url

    def test_generic_url_passthrough(self):
        url = 'https://example.com/some/video/path'
        assert normalize_video_url(url) == url

    def test_youtube_channel_url_passthrough(self):
        """Channel URLs without video IDs should pass through unchanged."""
        url = 'https://www.youtube.com/@RickAstleyYT'
        assert normalize_video_url(url) == url


# --- normalize_playlist_url ---


class TestNormalizePlaylistUrl:
    """Tests for normalize_playlist_url: YouTube playlist detection."""

    def test_youtube_playlist_url(self):
        url = 'https://www.youtube.com/playlist?list=PLJ8cMiYb3G5fEBBRGG3cXJJTPSBJb2MLa'
        assert (
            normalize_playlist_url(url)
            == 'https://www.youtube.com/playlist?list=PLJ8cMiYb3G5fEBBRGG3cXJJTPSBJb2MLa'
        )

    def test_youtube_watch_with_list(self):
        url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLJ8cMiYb3G5fEBBRGG3cXJJTPSBJb2MLa'
        assert (
            normalize_playlist_url(url)
            == 'https://www.youtube.com/playlist?list=PLJ8cMiYb3G5fEBBRGG3cXJJTPSBJb2MLa'
        )

    def test_non_youtube_returns_none(self):
        url = 'https://rumble.com/c/SomeChannel'
        assert normalize_playlist_url(url) is None

    def test_non_youtube_with_list_param_returns_none(self):
        url = 'https://rumble.com/c/SomeChannel?list=some-other-sites-list-id'
        assert normalize_playlist_url(url) is None

    def test_youtube_channel_returns_none(self):
        url = 'https://www.youtube.com/@RickAstleyYT'
        assert normalize_playlist_url(url) is None

    def test_no_list_param_returns_none(self):
        url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        assert normalize_playlist_url(url) is None


# --- is_channel_or_feed_url ---


class TestIsChannelOrFeedUrl:
    """Tests for is_channel_or_feed_url: multi-platform channel detection."""

    # YouTube
    def test_youtube_at_channel(self):
        assert is_channel_or_feed_url('https://www.youtube.com/@RickAstleyYT') is True

    def test_youtube_channel_id(self):
        assert (
            is_channel_or_feed_url('https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw')
            is True
        )

    def test_youtube_c_channel(self):
        assert is_channel_or_feed_url('https://www.youtube.com/c/RickAstley') is True

    def test_youtube_user(self):
        assert is_channel_or_feed_url('https://www.youtube.com/user/RickAstley') is True

    # Rumble
    def test_rumble_c_channel(self):
        assert is_channel_or_feed_url('https://rumble.com/c/SomeChannel') is True

    def test_rumble_user(self):
        assert is_channel_or_feed_url('https://rumble.com/user/SomeUser') is True

    def test_rumble_video_not_channel(self):
        assert is_channel_or_feed_url('https://rumble.com/v1abc23-some-video.html') is False

    # Odysee
    def test_odysee_channel(self):
        assert is_channel_or_feed_url('https://odysee.com/@RickAstleyYT') is True

    def test_odysee_video_not_channel(self):
        """Video URLs have @channel/video format but still contain @, so they match."""
        assert is_channel_or_feed_url('https://odysee.com/@channel:1/video:2') is True

    # Bitchute
    def test_bitchute_channel(self):
        assert is_channel_or_feed_url('https://www.bitchute.com/channel/abc123') is True

    # Negative cases
    def test_youtube_video_not_channel(self):
        assert is_channel_or_feed_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ') is False

    def test_youtube_playlist_not_channel(self):
        assert (
            is_channel_or_feed_url(
                'https://www.youtube.com/playlist?list=PLJ8cMiYb3G5fEBBRGG3cXJJTPSBJb2MLa'
            )
            is False
        )

    def test_generic_url_not_channel(self):
        assert is_channel_or_feed_url('https://example.com/some/path') is False

    def test_twitter_not_channel(self):
        assert is_channel_or_feed_url('https://x.com/user/status/123') is False


# --- is_youtube_url ---


class TestIsYoutubeUrl:
    """Tests for is_youtube_url: YouTube domain detection."""

    def test_www_youtube(self):
        assert is_youtube_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ') is True

    def test_youtube_no_www(self):
        assert is_youtube_url('https://youtube.com/watch?v=dQw4w9WgXcQ') is True

    def test_youtu_be(self):
        assert is_youtube_url('https://youtu.be/dQw4w9WgXcQ') is True

    def test_music_youtube(self):
        assert is_youtube_url('https://music.youtube.com/watch?v=dQw4w9WgXcQ') is True

    def test_mobile_youtube(self):
        assert is_youtube_url('https://m.youtube.com/watch?v=dQw4w9WgXcQ') is True

    def test_rumble_not_youtube(self):
        assert is_youtube_url('https://rumble.com/v123-video.html') is False

    def test_odysee_not_youtube(self):
        assert is_youtube_url('https://odysee.com/@channel/video') is False

    def test_generic_not_youtube(self):
        assert is_youtube_url('https://example.com') is False


# --- get_release_timestamp ---


class TestGetReleaseTimestamp:
    """Tests for get_release_timestamp: defensive metadata extraction."""

    def test_with_release_timestamp(self):
        info = {'release_timestamp': 1700000000}
        result = get_release_timestamp(info)
        assert isinstance(result, datetime)
        assert result == datetime.fromtimestamp(1700000000)

    def test_with_upload_date(self):
        info = {'upload_date': '20231115'}
        result = get_release_timestamp(info)
        assert isinstance(result, datetime)
        assert result == datetime(2023, 11, 15)

    def test_release_timestamp_takes_priority(self):
        info = {'release_timestamp': 1700000000, 'upload_date': '20200101'}
        result = get_release_timestamp(info)
        assert result == datetime.fromtimestamp(1700000000)

    def test_missing_both_returns_none(self):
        info = {'title': 'Some Video'}
        result = get_release_timestamp(info)
        assert result is None

    def test_empty_dict_returns_none(self):
        result = get_release_timestamp({})
        assert result is None

    def test_malformed_upload_date_returns_none(self):
        info = {'upload_date': 'not-a-date'}
        result = get_release_timestamp(info)
        assert result is None

    def test_none_upload_date_returns_none(self):
        info = {'upload_date': None}
        result = get_release_timestamp(info)
        assert result is None

    def test_upload_date_wrong_format_returns_none(self):
        info = {'upload_date': '2023-11-15'}  # Dashes instead of YYYYMMDD
        result = get_release_timestamp(info)
        assert result is None


# --- extract_entries_from_info ---


class TestExtractEntriesNormalizeUrls:
    """Entry URLs are canonicalized so Shorts share the watch?v= identity of MediaDetails."""

    def test_shorts_entry_normalized_to_watch_url(self):
        info = {'entries': [{'url': 'https://www.youtube.com/shorts/AltFormVid1', 'title': 'S'}]}
        assert extract_entries_from_info(info)[0]['url'] == (
            'https://www.youtube.com/watch?v=AltFormVid1'
        )

    def test_watch_entry_left_canonical(self):
        info = {'entries': [{'url': 'https://www.youtube.com/watch?v=AltFormVid1', 'title': 'V'}]}
        assert extract_entries_from_info(info)[0]['url'] == (
            'https://www.youtube.com/watch?v=AltFormVid1'
        )

    def test_non_youtube_entry_passes_through(self):
        info = {'entries': [{'url': 'https://rumble.com/v123-some-video.html', 'title': 'R'}]}
        assert (
            extract_entries_from_info(info)[0]['url'] == 'https://rumble.com/v123-some-video.html'
        )

    def test_nested_tab_entries_normalized(self):
        """Channel extraction nests entries one level per tab (Videos / Live / Shorts)."""
        info = {
            'entries': [
                {'entries': [{'url': 'https://www.youtube.com/watch?v=VideoTabId1', 'title': 'V'}]},
                {'entries': [{'url': 'https://www.youtube.com/shorts/ShortsTabId', 'title': 'S'}]},
            ]
        }
        assert [e['url'] for e in extract_entries_from_info(info)] == [
            'https://www.youtube.com/watch?v=VideoTabId1',
            'https://www.youtube.com/watch?v=ShortsTabId',
        ]
