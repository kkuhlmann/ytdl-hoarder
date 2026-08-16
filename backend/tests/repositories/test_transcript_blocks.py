import pytest
from sqlalchemy.exc import IntegrityError

from models import TranscriptBlock
from repositories import transcript_blocks


async def test_delete_transcript_block_by_media_details_id(test_database):
    # media_details_id=1 has 2 transcript blocks in test data
    assert await transcript_blocks.delete_transcript_block_by_media_details_id(1) == 2
    # Re-deleting finds nothing left, confirming the first call removed both
    assert await transcript_blocks.delete_transcript_block_by_media_details_id(1) == 0


def test_insert_transcript_block_with_invalid_media_details_id_fails(test_database):
    """Foreign key constraint should prevent inserting blocks with non-existent media_details_id."""
    orphan = TranscriptBlock(
        media_details_id=99999,
        start_time=10.0,
        end_time=15.0,
        text='This should fail.',
        transcript_model='tiny.en',
    )
    with pytest.raises(IntegrityError):
        transcript_blocks.sync_replace_transcript_blocks_with_embeddings(99999, [orphan], [])
