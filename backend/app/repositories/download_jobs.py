from database import db
from logger import logger
from models import DownloadJob

# --- Async functions for FastAPI ---


async def add_download_job(download_job: DownloadJob) -> DownloadJob:
    async with db.get_async_session() as session:
        session.add(download_job)
        await session.commit()
        await session.refresh(download_job)
        logger.debug(f'created_download: {download_job}')
        return download_job


# --- Sync functions (job bodies run in lane threads / the ML child) ---


def sync_add_download_job(download_job: DownloadJob) -> DownloadJob:
    with db.sync_session() as session:
        session.add(download_job)
        session.flush()
        session.refresh(download_job)
        return download_job
