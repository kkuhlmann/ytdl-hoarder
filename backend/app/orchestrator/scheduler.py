"""Cron scheduling for periodic jobs.

Two schedule shapes:
- every N minutes            → subscription checks (fires at wall-clock slots
                               anchored on midnight, at second 0)
- daily at hour:minute       → temp-file cleanup

The next-fire computations are pure functions (tested with frozen datetimes);
cron_loop drives them on the event loop and fires callbacks that submit jobs.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from logger import logger
from models import utc_now

MAX_INTERVAL_MINUTES = 24 * 60


def next_fire_every_n_minutes(now: datetime, n: int) -> datetime:
    """Next wall-clock-aligned fire time after `now` for an every-N-minutes schedule.

    Slots are anchored at midnight, so any N dividing 60 keeps clock alignment
    (N=10 → :00,:10,...) while N above 60 means what it says (N=120 → 00:00,
    02:00, ...) rather than collapsing to hourly. Times are UTC, so anchoring on
    the day boundary has no DST hazard.
    """
    n = max(1, min(MAX_INTERVAL_MINUTES, int(n)))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((now - midnight).total_seconds() // 60)
    return midnight + timedelta(minutes=(elapsed // n + 1) * n)


def next_fire_daily(now: datetime, hour: int, minute: int = 0) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


class IntervalSchedule:
    """An every-N-minutes schedule whose interval can change while cron_loop runs.

    `version` is what tells the loop a pending fire time is stale: the loop
    recomputes only after firing, so without it a change from 60 to 5 would not
    take effect until the top of the hour.
    """

    def __init__(self, minutes: int) -> None:
        self._minutes = self._clamp(minutes)
        self.version = 0

    @staticmethod
    def _clamp(minutes: int) -> int:
        return max(1, min(MAX_INTERVAL_MINUTES, int(minutes)))

    @property
    def minutes(self) -> int:
        return self._minutes

    def set_minutes(self, minutes: int) -> None:
        minutes = self._clamp(minutes)
        if minutes == self._minutes:
            return
        self._minutes = minutes
        self.version += 1

    def compute_next(self, now: datetime) -> datetime:
        return next_fire_every_n_minutes(now, self._minutes)


# Retargeted live by the settings router; seeded from app_settings at startup.
subscription_schedule = IntervalSchedule(10)


@dataclass
class CronJob:
    name: str
    compute_next: Callable[[datetime], datetime]
    # Fire callback; runs on the event loop, so it must only enqueue work
    # (orch submissions), never do blocking I/O itself.
    fire: Callable[[], None]
    # Opaque value that changes when the schedule is retargeted, invalidating
    # any fire time already computed from it.
    schedule_token: Callable[[], object] | None = None


def refresh_stale_schedules(
    jobs: list[CronJob],
    next_fires: dict[str, datetime],
    tokens: dict[str, object],
    now: datetime,
) -> list[str]:
    """Recompute the pending fire time of every job whose schedule token changed.

    Returns the names it rescheduled, for logging.
    """
    rescheduled = []
    for job in jobs:
        if job.schedule_token is None:
            continue
        token = job.schedule_token()
        if token == tokens.get(job.name):
            continue
        tokens[job.name] = token
        next_fires[job.name] = job.compute_next(now)
        rescheduled.append(job.name)
    return rescheduled


async def cron_loop(jobs: list[CronJob], is_running: Callable[[], bool]) -> None:
    """Fire each CronJob at its schedule until is_running() goes false."""
    next_fires = {job.name: job.compute_next(utc_now()) for job in jobs}
    tokens = {job.name: job.schedule_token() for job in jobs if job.schedule_token}
    for job in jobs:
        logger.info(f'Cron: {job.name} first fires at {next_fires[job.name]}')

    while is_running():
        now = utc_now()
        soonest = min(next_fires.values())
        wait = max(0.0, (soonest - now).total_seconds())
        try:
            await asyncio.sleep(min(wait, 30.0))
        except asyncio.CancelledError:
            return

        now = utc_now()
        # Before the due check, so a retarget replaces the pending fire rather
        # than racing it.
        for name in refresh_stale_schedules(jobs, next_fires, tokens, now):
            logger.info(f'Cron: {name} rescheduled, next fires at {next_fires[name]}')

        for job in jobs:
            if next_fires[job.name] <= now:
                next_fires[job.name] = job.compute_next(now)
                try:
                    job.fire()
                except Exception:
                    logger.exception(f'Cron job {job.name} failed to fire')
