"""Cron next-fire computations and live schedule retargeting."""

from datetime import datetime

from orchestrator.scheduler import (
    CronJob,
    IntervalSchedule,
    next_fire_daily,
    next_fire_every_n_minutes,
    refresh_stale_schedules,
)


def test_every_n_minutes_fires_on_aligned_minutes():
    # every-10-minutes semantics: :00, :10, :20 ...
    now = datetime(2026, 7, 13, 12, 3, 27)
    assert next_fire_every_n_minutes(now, 10) == datetime(2026, 7, 13, 12, 10, 0)


def test_every_n_minutes_on_boundary_moves_to_next_slot():
    # Already exactly on a slot → the NEXT slot (each slot fires once)
    now = datetime(2026, 7, 13, 12, 10, 0)
    assert next_fire_every_n_minutes(now, 10) == datetime(2026, 7, 13, 12, 20, 0)


def test_every_n_minutes_wraps_hour():
    now = datetime(2026, 7, 13, 12, 55, 30)
    assert next_fire_every_n_minutes(now, 10) == datetime(2026, 7, 13, 13, 0, 0)


def test_every_seven_minutes_anchors_on_midnight():
    # Slots run 00:00, 00:07, ... continuously through the day rather than
    # restarting each hour, so gaps stay uniform across an hour boundary.
    now = datetime(2026, 7, 13, 12, 8, 0)
    assert next_fire_every_n_minutes(now, 7) == datetime(2026, 7, 13, 12, 15, 0)
    now = datetime(2026, 7, 13, 12, 57, 0)
    assert next_fire_every_n_minutes(now, 7) == datetime(2026, 7, 13, 13, 4, 0)


def test_every_minute():
    now = datetime(2026, 7, 13, 12, 3, 27)
    assert next_fire_every_n_minutes(now, 1) == datetime(2026, 7, 13, 12, 4, 0)


def test_intervals_above_an_hour_are_not_collapsed_to_hourly():
    now = datetime(2026, 7, 13, 12, 3, 27)
    assert next_fire_every_n_minutes(now, 120) == datetime(2026, 7, 13, 14, 0, 0)
    assert next_fire_every_n_minutes(now, 360) == datetime(2026, 7, 13, 18, 0, 0)


def test_daily_interval_fires_at_midnight():
    now = datetime(2026, 7, 13, 12, 3, 27)
    assert next_fire_every_n_minutes(now, 1440) == datetime(2026, 7, 14, 0, 0, 0)


def test_every_n_minutes_wraps_the_day():
    now = datetime(2026, 7, 13, 23, 58, 12)
    assert next_fire_every_n_minutes(now, 10) == datetime(2026, 7, 14, 0, 0, 0)


def test_every_n_minutes_clamps_out_of_range_intervals():
    now = datetime(2026, 7, 13, 12, 3, 27)
    assert next_fire_every_n_minutes(now, 0) == next_fire_every_n_minutes(now, 1)
    assert next_fire_every_n_minutes(now, 99999) == next_fire_every_n_minutes(now, 1440)


def test_daily_before_the_hour():
    now = datetime(2026, 7, 13, 1, 30, 0)
    assert next_fire_daily(now, hour=3) == datetime(2026, 7, 13, 3, 0, 0)


def test_daily_after_the_hour_rolls_to_tomorrow():
    now = datetime(2026, 7, 13, 4, 0, 1)
    assert next_fire_daily(now, hour=3) == datetime(2026, 7, 14, 3, 0, 0)


def test_daily_exactly_at_fire_time_rolls_to_tomorrow():
    now = datetime(2026, 7, 13, 3, 0, 0)
    assert next_fire_daily(now, hour=3) == datetime(2026, 7, 14, 3, 0, 0)


class TestIntervalSchedule:
    def test_compute_next_follows_the_current_interval(self):
        schedule = IntervalSchedule(10)
        now = datetime(2026, 7, 13, 12, 3, 27)
        assert schedule.compute_next(now) == datetime(2026, 7, 13, 12, 10, 0)

        schedule.set_minutes(30)
        assert schedule.compute_next(now) == datetime(2026, 7, 13, 12, 30, 0)

    def test_version_bumps_only_on_a_real_change(self):
        schedule = IntervalSchedule(10)
        assert schedule.version == 0

        schedule.set_minutes(10)
        assert schedule.version == 0

        schedule.set_minutes(5)
        assert schedule.version == 1

    def test_out_of_range_minutes_are_clamped(self):
        assert IntervalSchedule(0).minutes == 1
        assert IntervalSchedule(99999).minutes == 1440


class TestRefreshStaleSchedules:
    @staticmethod
    def _job(schedule: IntervalSchedule) -> CronJob:
        return CronJob(
            name='subscriptions',
            compute_next=schedule.compute_next,
            fire=lambda: None,
            schedule_token=lambda: schedule.version,
        )

    def test_a_retarget_replaces_the_pending_fire_time(self):
        schedule = IntervalSchedule(60)
        job = self._job(schedule)
        now = datetime(2026, 7, 13, 12, 3, 27)
        next_fires = {job.name: job.compute_next(now)}
        tokens = {job.name: job.schedule_token()}
        assert next_fires['subscriptions'] == datetime(2026, 7, 13, 13, 0, 0)

        schedule.set_minutes(5)

        assert refresh_stale_schedules([job], next_fires, tokens, now) == ['subscriptions']
        assert next_fires['subscriptions'] == datetime(2026, 7, 13, 12, 5, 0)

    def test_an_unchanged_schedule_keeps_its_pending_fire_time(self):
        schedule = IntervalSchedule(60)
        job = self._job(schedule)
        now = datetime(2026, 7, 13, 12, 3, 27)
        next_fires = {job.name: job.compute_next(now)}
        tokens = {job.name: job.schedule_token()}

        later = datetime(2026, 7, 13, 12, 40, 0)
        assert refresh_stale_schedules([job], next_fires, tokens, later) == []
        assert next_fires['subscriptions'] == datetime(2026, 7, 13, 13, 0, 0)

    def test_jobs_without_a_token_are_left_alone(self):
        job = CronJob(
            name='cleanup-temp-files',
            compute_next=lambda now: next_fire_daily(now, hour=3),
            fire=lambda: None,
        )
        now = datetime(2026, 7, 13, 12, 3, 27)
        next_fires = {job.name: job.compute_next(now)}

        assert refresh_stale_schedules([job], next_fires, {}, now) == []
        assert next_fires['cleanup-temp-files'] == datetime(2026, 7, 14, 3, 0, 0)


def test_build_cron_jobs_shape():
    from tasks.registry import build_cron_jobs

    jobs = build_cron_jobs(15)
    names = {job.name for job in jobs}
    assert names == {
        'subscriptions-playlist_subscription',
        'subscriptions-channel_subscription',
        'cleanup-temp-files',
    }
    now = datetime(2026, 7, 13, 12, 3, 27)
    for job in jobs:
        assert job.compute_next(now) > now

    subscription_jobs = [job for job in jobs if job.name.startswith('subscriptions-')]
    for job in subscription_jobs:
        assert job.compute_next(now) == datetime(2026, 7, 13, 12, 15, 0)
        assert job.schedule_token is not None
