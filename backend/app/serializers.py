"""Serialization utilities for background-job payload passing.

DTOs are used instead of ORM models to avoid SQLAlchemy session issues and to
cleanly pass related data between tasks. Serialization is model_dump(mode='json')
— every DTO field is emitted, None included, because job bodies and hooks read
payload keys by subscript. Payloads are never durably stored (recovery
re-serializes from ORM rows), so the only compatibility contract is the
serialize→deserialize round trip pinned by tests/test_serializers.py.
"""

from models import DownloadJob, JobType, MediaDetails, Subscription
from schemas import DownloadJobDTO, MediaDetailsDTO, SubscriptionDTO


def serialize_subscription(sub: SubscriptionDTO) -> dict:
    return sub.model_dump(mode='json')


def serialize_media_details(md: MediaDetailsDTO) -> dict:
    return md.model_dump(mode='json')


def serialize_download_job(dl: DownloadJobDTO) -> dict:
    # Upgrade to PLAYLIST_DOWNLOAD for one-off playlist downloads to enable rate limiting
    if dl.download_playlist and dl.job_type == JobType.NORMAL_DOWNLOAD:
        dl = dl.model_copy(update={'job_type': JobType.PLAYLIST_DOWNLOAD})
    return dl.model_dump(mode='json')


def deserialize_subscription(data: dict) -> SubscriptionDTO:
    return SubscriptionDTO.model_validate(data)


def deserialize_media_details(data: dict) -> MediaDetailsDTO:
    return MediaDetailsDTO.model_validate(data)


def deserialize_download_job(data: dict) -> DownloadJobDTO:
    return DownloadJobDTO.model_validate(data)


# --- ORM conversion helpers ---


def subscription_to_dto(sub: Subscription) -> SubscriptionDTO:
    return SubscriptionDTO.from_orm(sub)


def media_details_to_dto(md: MediaDetails) -> MediaDetailsDTO:
    return MediaDetailsDTO.from_orm(md)


def download_job_to_dto(
    dl: DownloadJob,
    subscription: SubscriptionDTO | Subscription | None = None,
    media_details: MediaDetailsDTO | MediaDetails | None = None,
    pending_media_details: MediaDetailsDTO | MediaDetails | None = None,
    playlist_name: str | None = None,
) -> DownloadJobDTO:
    """Convert a DownloadJob ORM model to a DownloadJobDTO.

    Args:
        playlist_name: Used for subdirectory organization on disk.
    """

    def _md_dto(value):
        if value is None or isinstance(value, MediaDetailsDTO):
            return value
        return media_details_to_dto(value)

    sub_dto = (
        subscription
        if subscription is None or isinstance(subscription, SubscriptionDTO)
        else subscription_to_dto(subscription)
    )
    return DownloadJobDTO.from_orm(
        dl,
        subscription=sub_dto,
        media_details=_md_dto(media_details),
        pending_media_details=_md_dto(pending_media_details),
        playlist_name=playlist_name,
    )
