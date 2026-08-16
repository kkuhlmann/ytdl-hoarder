import repositories.task_records as task_repo
from logger import logger
from models import MediaDetails, TaskStatus
from orchestrator import JobCancelled, JobContext
from services.transcript import (
    TranscriptCancelled,
    add_embeddings,
    create_transcript_blocks,
)
from utils import load_embedding_model


def run_transcript_job(ctx: JobContext, md: dict):
    """Whisper transcription + embeddings (the transcription job body).

    Runs inside the spawned ML child process (orchestrator.child_main resolves
    the 'transcription' job to this function) — faster-whisper is imported
    lazily inside the service layer, so only that child process ever loads it.
    """
    logger.info(f'Creating transcript blocks for MediaDetails: {md}')
    # Pop force_recompute before constructing MediaDetails (not a model field)
    force_recompute = md.pop('force_recompute', False) if isinstance(md, dict) else False
    media_details = MediaDetails(**md) if isinstance(md, dict) else md
    task_id = ctx.task_id

    try:
        transcript_blocks = create_transcript_blocks(
            media_details, task_id=task_id, force_recompute=force_recompute
        )
    except TranscriptCancelled as e:
        logger.info(f'Transcript task {task_id} cancelled during block generation')
        ctx.skip_downstream = True
        msg = f'Transcript task {task_id} cancelled'
        raise JobCancelled(msg) from e
    except JobCancelled:
        raise
    except Exception as e:
        logger.exception(f'Transcript task {task_id} failed, retrying')
        ctx.retry(e)

    if not transcript_blocks:
        ctx.skip_downstream = True
        return

    # Final cancellation check before the atomic embeddings replace.
    # sync_replace_transcript_blocks_with_embeddings deletes old blocks and writes new
    # in one transaction, which would clobber any cancelled state if we proceeded blindly.
    record = task_repo.sync_get_task_by_task_id(task_id)
    if record is not None and record.status == TaskStatus.CANCELLED:
        logger.info(f'Transcript task {task_id} cancelled before embeddings persistence')
        ctx.skip_downstream = True
        msg = f'Transcript task {task_id} cancelled'
        raise JobCancelled(msg)

    add_embeddings(transcript_blocks, load_embedding_model())
