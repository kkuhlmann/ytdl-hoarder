from models import DownloadJob, JobType, MediaType
from repositories import download_jobs


async def test_add_download_job(test_database):
    created_download = await download_jobs.add_download_job(
        DownloadJob(
            url='https://www.youtube.com/watch?v=rgUrqGFxV3Q',
            audio_only=True,
            download_playlist=False,
            overwrite=False,
            media_type=MediaType.AUDIO,
            title='Test Video',
            job_type=JobType.NORMAL_DOWNLOAD,
            subscription_id=None,
            media_details_id=None,
        )
    )
    assert created_download is not None
    assert created_download.id is not None


def test_sync_add_download_job(test_database):
    created_download = download_jobs.sync_add_download_job(
        DownloadJob(
            url='https://www.youtube.com/watch?v=AC3Ejf7vPEY',
            audio_only=True,
            download_playlist=False,
            overwrite=False,
            media_type=MediaType.AUDIO,
            title='Sync Test Video',
            job_type=JobType.NORMAL_DOWNLOAD,
        )
    )
    assert created_download is not None
    assert created_download.id is not None
