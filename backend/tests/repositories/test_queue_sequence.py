"""The task_queue_sequence Postgres sequence behind TaskRecord.queue_sequence."""

from repositories import task_records as tr_repo


def test_sync_queue_sequence_is_monotonic(test_database):
    first = tr_repo.sync_get_next_queue_sequence()
    second = tr_repo.sync_get_next_queue_sequence()
    assert second == first + 1


async def test_async_queue_sequence_shares_series_with_sync(test_database):
    start = tr_repo.sync_get_next_queue_sequence()
    via_async = await tr_repo.get_next_queue_sequence()
    assert via_async == start + 1
