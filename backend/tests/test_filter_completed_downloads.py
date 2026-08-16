"""DB-backed tests for filter_completed_downloads cross-user dedup.

Proves the load-bearing assumption behind per-user subscriptions: a second
subscriber to already-downloaded content gets a MediaAccess grant instead of
a second physical download.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from database import db
from models import (
    JobType,
    MediaAccess,
    MediaDetails,
    MediaType,
    SourceType,
    Subscription,
    SubscriptionAccess,
    TaskStatus,
    User,
    utc_now,
)
from schemas import DownloadJobDTO, SubscriptionDTO
from serializers import serialize_download_job
from tasks.media import filter_completed_downloads_impl as filter_completed_downloads

DEDUP_URL = 'https://www.youtube.com/watch?v=dedup123'


def _seed_owner_media_and_second_subscriber(md_status=TaskStatus.COMPLETE):
    """Owner A with existing media + user B owning a subscription to the same channel."""
    session = db.get_sync_session()
    try:
        owner = User(username='owner_a', password_hash='x', is_approved=True)
        second = User(username='subscriber_b', password_hash='x', is_approved=True)
        session.add(owner)
        session.add(second)
        session.commit()
        session.refresh(owner)
        session.refresh(second)

        sub = Subscription(
            url='https://www.youtube.com/@DedupChannel',
            channel='DedupChannel',
            audio_only=True,
            media_type=MediaType.AUDIO,
            job_type=JobType.CHANNEL_SUBSCRIPTION,
            user_id=second.id,
        )
        md = MediaDetails(
            url=DEDUP_URL,
            media_type=MediaType.AUDIO,
            channel='DedupChannel',
            title='Already Downloaded',
            status=md_status,
            release_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            owner_id=owner.id,
        )
        session.add(sub)
        session.add(md)
        session.commit()
        session.refresh(sub)
        session.refresh(md)
        return owner.id, second.id, sub.id, md.id
    finally:
        session.close()


def _seed_shared_subscription_user(subscription_id):
    """A third user with shared access to the given subscription."""
    session = db.get_sync_session()
    try:
        shared = User(username='shared_c', password_hash='x', is_approved=True)
        session.add(shared)
        session.commit()
        session.refresh(shared)
        session.add(SubscriptionAccess(user_id=shared.id, subscription_id=subscription_id))
        session.commit()
        return shared.id
    finally:
        session.close()


def _count_media_access(user_id, media_id, source_type, source_id):
    session = db.get_sync_session()
    try:
        stmt = select(MediaAccess).where(
            MediaAccess.user_id == user_id,
            MediaAccess.media_details_id == media_id,
            MediaAccess.source_type == source_type,
            MediaAccess.source_id == source_id,
        )
        return len(session.execute(stmt).scalars().all())
    finally:
        session.close()


def _count_all_media_access(media_id):
    session = db.get_sync_session()
    try:
        stmt = select(MediaAccess).where(MediaAccess.media_details_id == media_id)
        return len(session.execute(stmt).scalars().all())
    finally:
        session.close()


def test_second_subscriber_gets_access_grant_instead_of_download(test_database):
    _owner_id, second_id, sub_id, md_id = _seed_owner_media_and_second_subscriber()

    dto = DownloadJobDTO(
        url=DEDUP_URL,
        media_type=MediaType.AUDIO,
        user_id=second_id,
        subscription_id=sub_id,
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    # No download queued for already-downloaded media
    assert result == []
    # ...but the second subscriber got subscription-sourced access
    assert _count_media_access(second_id, md_id, SourceType.SUBSCRIPTION, sub_id) == 1


def test_second_subscriber_deleted_media_triggers_redownload(test_database):
    """A non-owner's job for DELETED media is included for re-download, with no dead grant."""
    _owner_id, second_id, sub_id, md_id = _seed_owner_media_and_second_subscriber(
        md_status=TaskStatus.DELETED
    )

    dto = DownloadJobDTO(
        url=DEDUP_URL,
        media_type=MediaType.AUDIO,
        user_id=second_id,
        subscription_id=sub_id,
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    # Job passes the filter so the media gets re-downloaded fresh
    assert len(result) == 1
    assert result[0]['url'] == DEDUP_URL
    # No access row granted to the file-less dead record
    assert _count_all_media_access(md_id) == 0


def test_owner_deleted_media_still_skipped_without_grants(test_database):
    """The owner's own job for their DELETED media stays skipped, and shared-subscription
    users get no dead access rows either."""
    owner_id, _second_id, sub_id, md_id = _seed_owner_media_and_second_subscriber(
        md_status=TaskStatus.DELETED
    )
    _seed_shared_subscription_user(sub_id)

    dto = DownloadJobDTO(
        url=DEDUP_URL,
        media_type=MediaType.AUDIO,
        user_id=owner_id,
        subscription_id=sub_id,
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    assert result == []
    assert _count_all_media_access(md_id) == 0


def test_owner_overwrite_deleted_media_included(test_database):
    """Owner semantics preserved: overwrite still forces a re-download of DELETED media."""
    owner_id, _second_id, sub_id, _md_id = _seed_owner_media_and_second_subscriber(
        md_status=TaskStatus.DELETED
    )

    dto = DownloadJobDTO(
        url=DEDUP_URL,
        media_type=MediaType.AUDIO,
        user_id=owner_id,
        subscription_id=sub_id,
        overwrite=True,
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    assert len(result) == 1
    assert result[0]['url'] == DEDUP_URL


DURATION_SKIPPED_URL = 'https://www.youtube.com/watch?v=shortvid123'


def _seed_duration_skipped_media(duration, min_duration_seconds=60, max_duration_seconds=None):
    """Owner with a subscription enforcing a duration filter + a SKIPPED media row."""
    session = db.get_sync_session()
    try:
        owner = User(username='owner_duration', password_hash='x', is_approved=True)
        session.add(owner)
        session.commit()
        session.refresh(owner)

        sub = Subscription(
            url='https://www.youtube.com/@DurationChannel',
            channel='DurationChannel',
            audio_only=True,
            media_type=MediaType.AUDIO,
            job_type=JobType.CHANNEL_SUBSCRIPTION,
            user_id=owner.id,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
        )
        md = MediaDetails(
            url=DURATION_SKIPPED_URL,
            media_type=MediaType.AUDIO,
            channel='DurationChannel',
            title='Too Short',
            status=TaskStatus.SKIPPED,
            duration=duration,
            owner_id=owner.id,
        )
        session.add(sub)
        session.add(md)
        session.commit()
        session.refresh(sub)
        session.refresh(md)
        return owner.id, sub.id, md.id
    finally:
        session.close()


def _get_subscription_dto(sub_id):
    """Fetch the current subscription row as a SubscriptionDTO, mirroring how
    create_download_jobs_from_subs embeds it directly into the DownloadJobDTO."""
    session = db.get_sync_session()
    try:
        sub = session.get(Subscription, sub_id)
        return SubscriptionDTO.from_orm(sub)
    finally:
        session.close()


def test_duration_skipped_media_still_filtered_stays_skipped(test_database):
    """A too-short video re-discovered by a scan stays SKIPPED without any churn."""
    owner_id, sub_id, _md_id = _seed_duration_skipped_media(duration=30, min_duration_seconds=60)

    dto = DownloadJobDTO(
        url=DURATION_SKIPPED_URL,
        media_type=MediaType.AUDIO,
        user_id=owner_id,
        subscription_id=sub_id,
        subscription=_get_subscription_dto(sub_id),
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    assert result == []


def test_duration_skipped_media_filter_loosened_included(test_database):
    """Loosening the subscription's duration filter re-admits a previously SKIPPED video."""
    owner_id, sub_id, _md_id = _seed_duration_skipped_media(duration=30, min_duration_seconds=60)

    # Loosen the filter so the 30s video now qualifies
    session = db.get_sync_session()
    try:
        sub = session.get(Subscription, sub_id)
        sub.min_duration_seconds = 10
        session.add(sub)
        session.commit()
    finally:
        session.close()

    dto = DownloadJobDTO(
        url=DURATION_SKIPPED_URL,
        media_type=MediaType.AUDIO,
        user_id=owner_id,
        subscription_id=sub_id,
        subscription=_get_subscription_dto(sub_id),
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    assert len(result) == 1
    assert result[0]['url'] == DURATION_SKIPPED_URL


def test_duration_skipped_media_unknown_duration_not_blocked(test_database):
    """A SKIPPED row with no stored duration isn't held back by the duration re-check."""
    owner_id, sub_id, _md_id = _seed_duration_skipped_media(duration=None, min_duration_seconds=60)

    dto = DownloadJobDTO(
        url=DURATION_SKIPPED_URL,
        media_type=MediaType.AUDIO,
        user_id=owner_id,
        subscription_id=sub_id,
        subscription=_get_subscription_dto(sub_id),
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    assert len(result) == 1
    assert result[0]['url'] == DURATION_SKIPPED_URL


ALT_FORM_VIDEO_ID = 'AltFormVid1'
ALT_FORM_CANONICAL_URL = f'https://www.youtube.com/watch?v={ALT_FORM_VIDEO_ID}'


def _seed_date_skipped_media(url=ALT_FORM_CANONICAL_URL):
    """Owner with a date-filtered subscription + a SKIPPED media row predating the filter."""
    session = db.get_sync_session()
    try:
        owner = User(username='owner_altform', password_hash='x', is_approved=True)
        session.add(owner)
        session.commit()
        session.refresh(owner)

        sub = Subscription(
            url='https://www.youtube.com/@AltFormChannel',
            channel='AltFormChannel',
            audio_only=False,
            media_type=MediaType.VIDEO,
            job_type=JobType.CHANNEL_SUBSCRIPTION,
            user_id=owner.id,
            date_filter=datetime(2026, 1, 1),
        )
        md = MediaDetails(
            url=url,
            media_type=MediaType.VIDEO,
            channel='AltFormChannel',
            title='An Old Short',
            status=TaskStatus.SKIPPED,
            release_timestamp=datetime(2024, 6, 1),
            duration=44,
            owner_id=owner.id,
        )
        session.add(sub)
        session.add(md)
        session.commit()
        session.refresh(sub)
        session.refresh(md)
        return owner.id, sub.id, md.id
    finally:
        session.close()


@pytest.mark.parametrize(
    'job_url',
    [
        f'https://www.youtube.com/shorts/{ALT_FORM_VIDEO_ID}',
        f'https://youtu.be/{ALT_FORM_VIDEO_ID}',
        f'https://www.youtube.com/watch?v={ALT_FORM_VIDEO_ID}',
    ],
)
def test_non_canonical_url_forms_match_existing_skipped_media(test_database, job_url):
    """Every URL form of one video resolves to the same SKIPPED row.

    yt-dlp yields Shorts as /shorts/<id> while MediaDetails only ever stores the
    canonical watch?v=<id>. Without normalizing the lookup key the filter misses,
    and populate then deletes + re-fetches + re-inserts the row on every scan.
    """
    owner_id, sub_id, _md_id = _seed_date_skipped_media()

    dto = DownloadJobDTO(
        url=job_url,
        media_type=MediaType.VIDEO,
        user_id=owner_id,
        subscription_id=sub_id,
        subscription=_get_subscription_dto(sub_id),
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    assert result == []


def test_playlist_expansion_job_url_left_untouched(test_database):
    """A not-yet-expanded playlist job keeps its list= param through the filter.

    normalize_video_url would strip list= from watch?v=X&list=PL, which is what
    expand_playlists_impl keys on — so download_playlist jobs must pass through raw.
    """
    owner_id, sub_id, _md_id = _seed_date_skipped_media()
    playlist_job_url = 'https://www.youtube.com/watch?v=SomeVideoId&list=PLtestlist123'

    dto = DownloadJobDTO(
        url=playlist_job_url,
        media_type=MediaType.VIDEO,
        user_id=owner_id,
        subscription_id=sub_id,
        download_playlist=True,
    )
    result = filter_completed_downloads([serialize_download_job(dto)])

    assert len(result) == 1
    assert result[0]['url'] == playlist_job_url


DEFERRED_URL = 'https://www.youtube.com/watch?v=premiere123'


def _seed_deferred_media(next_check_at, url=DEFERRED_URL):
    """Owner + subscription + a NOT_READY row parked until next_check_at."""
    session = db.get_sync_session()
    try:
        owner = User(username=f'owner_deferred_{url[-3:]}', password_hash='x', is_approved=True)
        session.add(owner)
        session.commit()
        session.refresh(owner)

        sub = Subscription(
            url='https://www.youtube.com/@DeferChannel',
            channel='DeferChannel',
            audio_only=True,
            media_type=MediaType.AUDIO,
            job_type=JobType.CHANNEL_SUBSCRIPTION,
            user_id=owner.id,
        )
        md = MediaDetails(
            url=url,
            media_type=MediaType.AUDIO,
            channel='DeferChannel',
            title='Upcoming Premiere',
            status=TaskStatus.NOT_READY,
            release_timestamp=datetime(2099, 1, 1),
            next_check_at=next_check_at,
            owner_id=owner.id,
        )
        session.add(sub)
        session.add(md)
        session.commit()
        session.refresh(sub)
        return owner.id, sub.id
    finally:
        session.close()


def _deferred_job(owner_id, sub_id, url=DEFERRED_URL, **overrides):
    fields = {
        'url': url,
        'media_type': MediaType.AUDIO,
        'user_id': owner_id,
        'subscription_id': sub_id,
    }
    fields.update(overrides)
    return serialize_download_job(DownloadJobDTO(**fields))


def test_deferred_media_is_held_until_its_next_check(test_database):
    """The recurring-spike fix: a parked premiere costs no yt-dlp call this tick."""
    owner_id, sub_id = _seed_deferred_media(utc_now() + timedelta(hours=6))

    result = filter_completed_downloads([_deferred_job(owner_id, sub_id)])

    assert result == []


def test_deferred_media_is_rechecked_once_due(test_database):
    owner_id, sub_id = _seed_deferred_media(utc_now() - timedelta(minutes=1))

    result = filter_completed_downloads([_deferred_job(owner_id, sub_id)])

    assert len(result) == 1
    assert result[0]['url'] == DEFERRED_URL


def test_deferred_media_without_a_check_time_is_due_now(test_database):
    """Rows predating the column must not be parked forever."""
    owner_id, sub_id = _seed_deferred_media(None)

    result = filter_completed_downloads([_deferred_job(owner_id, sub_id)])

    assert len(result) == 1


def test_direct_download_bypasses_the_deferral(test_database):
    """A user asking for this URL now must not be silently dropped because a
    subscription parked it for a week."""
    owner_id, sub_id = _seed_deferred_media(utc_now() + timedelta(days=7))

    result = filter_completed_downloads([_deferred_job(owner_id, sub_id, subscription_id=None)])

    assert len(result) == 1


def test_batched_lookup_spans_mixed_media_types(test_database):
    """Batching groups by media_type; a VIDEO job must not match an AUDIO row."""
    owner_id, sub_id = _seed_deferred_media(utc_now() + timedelta(hours=6))

    result = filter_completed_downloads(
        [
            _deferred_job(owner_id, sub_id),
            _deferred_job(owner_id, sub_id, media_type=MediaType.VIDEO),
        ]
    )

    assert [job['media_type'] for job in result] == ['VIDEO']


CANCELLED_URL = 'https://www.youtube.com/watch?v=cancelled99'


def _seed_cancelled_download(md_status):
    """A subscription video whose download task the user cancelled."""
    session = db.get_sync_session()
    try:
        owner = User(username='owner_cancel', password_hash='x', is_approved=True)
        session.add(owner)
        session.commit()
        session.refresh(owner)

        sub = Subscription(
            url='https://www.youtube.com/@CancelChannel',
            channel='CancelChannel',
            audio_only=True,
            media_type=MediaType.AUDIO,
            job_type=JobType.CHANNEL_SUBSCRIPTION,
            user_id=owner.id,
        )
        md = MediaDetails(
            url=CANCELLED_URL,
            media_type=MediaType.AUDIO,
            channel='CancelChannel',
            title='Cancelled Video',
            status=md_status,
            release_timestamp=datetime(2025, 1, 1),
            owner_id=owner.id,
        )
        session.add(sub)
        session.add(md)
        session.commit()
        session.refresh(sub)
        return owner.id, sub.id
    finally:
        session.close()


def test_cancelled_download_stops_being_refanned(test_database):
    """The production loop: cancel left status NONE, which the filter re-includes on
    every tick forever. A terminal CANCELLED status ends it."""
    owner_id, sub_id = _seed_cancelled_download(TaskStatus.CANCELLED)

    job = serialize_download_job(
        DownloadJobDTO(
            url=CANCELLED_URL,
            media_type=MediaType.AUDIO,
            user_id=owner_id,
            subscription_id=sub_id,
        )
    )

    assert filter_completed_downloads([job]) == []


def test_status_none_is_still_refanned(test_database):
    """Guards the diagnosis itself: NONE is what made the loop possible, so if this
    ever starts passing the root cause has moved and the fix above is misdirected."""
    owner_id, sub_id = _seed_cancelled_download(TaskStatus.NONE)

    job = serialize_download_job(
        DownloadJobDTO(
            url=CANCELLED_URL,
            media_type=MediaType.AUDIO,
            user_id=owner_id,
            subscription_id=sub_id,
        )
    )

    assert len(filter_completed_downloads([job])) == 1


def test_direct_download_bypasses_cancelled_media(test_database):
    """A cancel leaves no file, so a user re-requesting the URL now must not be dropped
    as 'already in your library'. Subscriptions still skip it — see the test above."""
    owner_id, _ = _seed_cancelled_download(TaskStatus.CANCELLED)

    job = serialize_download_job(
        DownloadJobDTO(
            url=CANCELLED_URL,
            media_type=MediaType.AUDIO,
            user_id=owner_id,
        )
    )

    assert len(filter_completed_downloads([job])) == 1
