"""Round-trip and shape tests for job-payload serialization.

Written against the hand-rolled serializers first (all green), they define the
contract the model_dump/model_validate rewrite must keep.
"""

from datetime import datetime

from models import AudioQuality, DownloadQuality, JobType, MediaType, TaskStatus
from schemas import DownloadJobDTO, MediaDetailsDTO, SubscriptionDTO
from serializers import (
    deserialize_download_job,
    deserialize_media_details,
    deserialize_subscription,
    serialize_download_job,
    serialize_media_details,
    serialize_subscription,
)


def _full_subscription() -> SubscriptionDTO:
    return SubscriptionDTO(
        id=3,
        url='https://youtube.com/@chan',
        channel='Chan',
        enabled=False,
        audio_only=True,
        media_type=MediaType.AUDIO,
        string_match='mix',
        overwrite=False,
        date_filter=datetime(2025, 6, 1, 12, 30),
        min_duration_seconds=60,
        max_duration_seconds=None,
        job_type=JobType.CHANNEL_SUBSCRIPTION,
        generate_transcript=True,
        download_quality=DownloadQuality.BEST,
        audio_quality=AudioQuality.K128,
        user_id=1,
    )


def _full_media_details() -> MediaDetailsDTO:
    return MediaDetailsDTO(
        id=9,
        url='https://youtube.com/watch?v=abc',
        media_type=MediaType.AUDIO,
        channel='Chan',
        title='Song',
        status=TaskStatus.NONE,
        release_timestamp=datetime(2025, 5, 1, 8, 0),
        duration=123.4,
        owner_id=1,
    )


def test_subscription_round_trip():
    dto = _full_subscription()
    assert deserialize_subscription(serialize_subscription(dto)) == dto


def test_media_details_round_trip():
    dto = _full_media_details()
    assert deserialize_media_details(serialize_media_details(dto)) == dto


def test_download_job_round_trip_with_nested():
    dto = DownloadJobDTO(
        id=5,
        url='https://youtube.com/watch?v=abc',
        audio_only=True,
        media_type=MediaType.AUDIO,
        job_type=JobType.CHANNEL_SUBSCRIPTION,
        subscription=_full_subscription(),
        media_details=_full_media_details(),
        pending_media_details=_full_media_details(),
        playlist_name='Mixes',
        source_playlist_url='https://youtube.com/playlist?list=x',
        user_id=1,
    )
    assert deserialize_download_job(serialize_download_job(dto)) == dto


def test_serialized_values_are_json_primitives():
    data = serialize_download_job(
        DownloadJobDTO(
            url='https://x', media_type=MediaType.VIDEO, subscription=_full_subscription()
        )
    )
    assert data['media_type'] == 'VIDEO'
    assert data['job_type'] == 'NORMAL_DOWNLOAD'
    assert data['subscription']['date_filter'] == '2025-06-01T12:30:00'
    assert data['subscription']['audio_quality'] == '128K'


def test_media_details_values_are_json_primitives():
    data = serialize_media_details(_full_media_details())
    assert data['media_type'] == 'AUDIO'
    assert data['status'] == 'NONE'
    assert data['release_timestamp'] == '2025-05-01T08:00:00'


def test_playlist_download_upgrade():
    # One-off playlist downloads are upgraded so rate limiting sees them.
    dto = DownloadJobDTO(url='https://x', download_playlist=True)
    assert serialize_download_job(dto)['job_type'] == 'PLAYLIST_DOWNLOAD'
    # ...but an explicit non-NORMAL job_type is left alone.
    dto2 = DownloadJobDTO(
        url='https://x', download_playlist=True, job_type=JobType.CHANNEL_SUBSCRIPTION
    )
    assert serialize_download_job(dto2)['job_type'] == 'CHANNEL_SUBSCRIPTION'


def test_scalar_none_keys_stay_present():
    # TranscriptHooks reads md['title'] by subscript — None must be present, not absent.
    data = serialize_media_details(MediaDetailsDTO(url='https://x', media_type=MediaType.AUDIO))
    assert 'title' in data and data['title'] is None
    assert 'channel' in data and data['channel'] is None


def test_embedded_keys_present_as_none_when_absent():
    # model_dump emits every field; consumers use `.get(...) or {}`.
    data = serialize_download_job(DownloadJobDTO(url='https://x'))
    assert 'media_details' in data and data['media_details'] is None
    assert 'playlist_name' in data and data['playlist_name'] is None


def test_deserialize_tolerates_absent_optional_keys():
    # Old payload shape: falsy embedded keys were omitted entirely.
    dto = deserialize_download_job({'url': 'https://x', 'media_type': 'AUDIO'})
    assert dto.subscription is None
    assert dto.media_details is None
    assert dto.playlist_name is None
