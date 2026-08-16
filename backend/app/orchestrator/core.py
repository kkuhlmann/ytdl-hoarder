"""The orchestrator: the in-process engine for all background work.

One instance lives inside the uvicorn process (started from the FastAPI
lifespan). It owns four lanes (default / subscriptions / downloads / ml), an
in-memory priority queue per lane, and an ephemeral result registry for jobs
that have no TaskRecord.

Threading model:
- The event loop runs dispatchers and all queue mutations.
- Job bodies run in lane worker threads (asyncio.to_thread) or, for
  transcription, in a spawned child process managed from a worker thread.
- Worker threads talk back via loop.call_soon_threadsafe (submissions) and
  plain DB writes (status).

Durability: Postgres TaskRecord is the only durable state. Queues are rebuilt
from it at startup (orchestrator.recovery), so queued and interrupted work
survives restarts.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass

from logger import logger
from models import TaskStatus
from repositories import task_records as tr_repo

from . import wrapper
from .jobs import (
    DEFAULT_LANE_CONCURRENCY,
    JobSpec,
    get_job_definition,
)
from .lanes import JobHandle, Lane, QueueEntry

# How long finished-job states stay queryable via get_status.
RESULT_TTL_SECONDS = 3600
# Absolute cap for any registry entry (protects against abandoned PENDING ids).
RESULT_MAX_AGE_SECONDS = 86400

# Job state strings served by GET /tasks/{task_id}; the frontend polls them
# (frontend/app/jobStatusService.ts) for jobs without TaskRecords.
_TERMINAL_STATES = {'SUCCESS', 'FAILURE', 'REVOKED'}

_TASKSTATUS_TO_STATE = {
    TaskStatus.NONE: 'PENDING',
    TaskStatus.QUEUED: 'PENDING',
    TaskStatus.IN_PROGRESS: 'STARTED',
    TaskStatus.POSTPROCESSING: 'STARTED',
    TaskStatus.COMPLETE: 'SUCCESS',
    TaskStatus.RETRY: 'RETRY',
    TaskStatus.FAILED: 'FAILURE',
    TaskStatus.UPSTREAM_FAILED: 'FAILURE',
    TaskStatus.CANCELLED: 'REVOKED',
    TaskStatus.SKIPPED: 'REVOKED',
    TaskStatus.DELETED: 'REVOKED',
    TaskStatus.NOT_READY: 'PENDING',
}

_OUTCOME_TO_STATE = {
    wrapper.SUCCESS: 'SUCCESS',
    wrapper.SKIPPED: 'REVOKED',
    wrapper.CANCELLED: 'REVOKED',
    wrapper.RETRY: 'RETRY',
    wrapper.FAILURE: 'FAILURE',
    # wrapper.SHUTDOWN deliberately records nothing — recovery resumes the job.
}


def map_task_status_to_state(status: TaskStatus) -> str:
    return _TASKSTATUS_TO_STATE.get(status, 'PENDING')


@dataclass
class _ResultEntry:
    state: str
    updated: float
    terminal: bool
    # Submitting user, so untracked jobs (no TaskRecord to check) can still be
    # ownership-checked by GET /tasks/{task_id}.
    user_id: int | None = None


class OrchestratorNotRunningError(RuntimeError):
    pass


class Orchestrator:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._stopping = False
        self._lanes: dict[str, Lane] = {}
        self._handles: dict[str, JobHandle] = {}
        self._results: dict[str, _ResultEntry] = {}
        self._dispatchers: list[asyncio.Task] = []
        self._services: list[asyncio.Task] = []
        self._job_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ state

    @property
    def running(self) -> bool:
        return self._running

    @property
    def stopping(self) -> bool:
        return self._stopping

    # -------------------------------------------------------------- lifecycle

    async def start(self, concurrency: dict[str, int] | None = None) -> None:
        """Create lanes and start dispatchers. Idempotent.

        `concurrency` maps lane name to width; missing lanes fall back to
        DEFAULT_LANE_CONCURRENCY. The caller supplies it (main.py reads the
        app_settings row) so the orchestrator depends on neither config nor a
        repository.
        """
        if self._running:
            return
        widths = {**DEFAULT_LANE_CONCURRENCY, **(concurrency or {})}

        self._loop = asyncio.get_running_loop()
        self._stopping = False
        self._running = True
        self._lanes = {name: Lane(name, max(1, widths[name])) for name in DEFAULT_LANE_CONCURRENCY}
        self._dispatchers = [
            asyncio.create_task(self._dispatch_loop(lane), name=f'orch-lane-{name}')
            for name, lane in self._lanes.items()
        ]
        lane_summary = ', '.join(f'{n}×{lane.concurrency}' for n, lane in self._lanes.items())
        logger.info(f'Orchestrator started (lanes: {lane_summary})')

    def add_service(self, coro, name: str) -> None:
        """Attach a background service coroutine (retry scheduler, cron, ...)."""
        self._services.append(asyncio.create_task(coro, name=name))

    async def stop(self, job_grace: float = 10.0) -> None:
        """Stop dispatchers and signal shutdown-cancel to running jobs.

        Running jobs get `job_grace` seconds to notice their cancel event
        (downloads abort at the next progress tick, the ML child is SIGTERM'd).
        Whatever survives stays IN_PROGRESS in the DB and is resumed by startup
        recovery on the next boot.
        """
        if not self._running:
            return
        self._running = False
        self._stopping = True

        for task in self._services:
            task.cancel()
        for lane in self._lanes.values():
            lane.wakeup.set()
        for task in self._dispatchers:
            task.cancel()
        await asyncio.gather(*self._services, *self._dispatchers, return_exceptions=True)
        self._services = []
        self._dispatchers = []

        running_handles = [h for h in self._handles.values() if h.state == 'RUNNING']
        if running_handles:
            logger.info(
                f'Signalling shutdown to {len(running_handles)} running job(s); '
                f'unfinished work resumes on next startup'
            )
            for handle in running_handles:
                handle.shutdown = True
                if handle.cancel_event is not None:
                    handle.cancel_event.set()
        if self._job_tasks:
            await asyncio.wait(set(self._job_tasks), timeout=job_grace)

        logger.info('Orchestrator stopped')

    # ------------------------------------------------------------- submission

    async def submit(self, spec: JobSpec) -> str:
        """Enqueue a job from the event loop. Returns its task_id."""
        return self._submit_nowait(spec)

    def submit_from_thread(self, spec: JobSpec) -> str:
        """Enqueue a job from a worker thread. Returns its task_id immediately."""
        if not self._running or self._loop is None:
            msg = 'orchestrator is not running'
            raise OrchestratorNotRunningError(msg)
        if spec.task_id is None:
            spec.task_id = str(uuid.uuid4())
        self._loop.call_soon_threadsafe(self._submit_threadsafe, spec)
        return spec.task_id

    def _submit_threadsafe(self, spec: JobSpec) -> None:
        try:
            self._submit_nowait(spec)
        except Exception:
            logger.exception(f'Dropped job {spec.job_name} ({spec.task_id})')

    def _submit_nowait(self, spec: JobSpec) -> str:
        """Enqueue on the loop thread. All queue mutations happen here."""
        if not self._running:
            msg = 'orchestrator is not running'
            raise OrchestratorNotRunningError(msg)
        definition = get_job_definition(spec.job_name)
        if spec.task_id is None:
            spec.task_id = str(uuid.uuid4())
        if spec.task_id in self._handles:
            # Idempotence guard: recovery/retry double-fires must not duplicate.
            logger.info(f'Job {spec.task_id} already queued or running; ignoring resubmit')
            return spec.task_id

        import threading

        lane = self._lanes[definition.lane]
        handle = JobHandle(
            task_id=spec.task_id,
            spec=spec,
            lane=definition.lane,
            cancel_event=threading.Event(),
        )
        self._handles[spec.task_id] = handle
        self._set_result(spec.task_id, 'PENDING', user_id=spec.user_id)
        lane.add(QueueEntry(spec=spec, handle=handle))
        self._sweep_results()
        return spec.task_id

    # ------------------------------------------------------------ dispatching

    async def _dispatch_loop(self, lane: Lane) -> None:
        try:
            while self._running:
                while self._running and not lane.entries:
                    lane.wakeup.clear()
                    await lane.wakeup.wait()
                if not self._running:
                    return
                await lane.slots.acquire()
                if lane.absorb_surplus_permit():
                    # Lane was narrowed; retire this permit instead of using it.
                    continue
                entry = lane.pop_next()
                if entry is None:
                    # Queue drained (cancel) while waiting for a slot.
                    lane.slots.release()
                    continue
                entry.handle.state = 'RUNNING'
                lane.running[entry.handle.task_id] = entry
                task = asyncio.create_task(
                    self._run_entry(lane, entry),
                    name=f'orch-job-{entry.spec.job_name}-{entry.handle.task_id[:8]}',
                )
                self._job_tasks.add(task)
                task.add_done_callback(self._job_tasks.discard)
        except asyncio.CancelledError:
            return

    async def _run_entry(self, lane: Lane, entry: QueueEntry) -> None:
        spec = entry.spec
        handle = entry.handle
        task_id = handle.task_id
        self._set_result(task_id, 'STARTED')
        crashed = False
        try:
            definition = get_job_definition(spec.job_name)
            outcome = await asyncio.to_thread(wrapper.run_job_sync, definition, spec, handle)
        except Exception as e:
            # run_job_sync absorbs body *and* hook exceptions; reaching here
            # means the thread never ran it. Never let it kill the lane.
            logger.exception(f'Job wrapper crashed for {task_id}')
            crashed = True
            outcome = wrapper.Outcome(
                wrapper.FAILURE,
                error=e,
                terminal_patch={
                    'status': TaskStatus.FAILED,
                    'status_message': f'Task failed: {e}',
                },
            )
        finally:
            lane.running.pop(task_id, None)
            self._handles.pop(task_id, None)
            lane.slots.release()

        if crashed and spec.tracked:
            # Write the terminal status the wrapper never reached, or the row
            # spins in the tasks table until the next restart. Deliberately
            # after the slot release: a DB that is hanging must not stall a lane.
            await asyncio.to_thread(wrapper.reconcile_terminal_status, task_id, outcome)

        state = _OUTCOME_TO_STATE.get(outcome.kind)
        if state is not None:
            self._set_result(task_id, state)

        if (
            outcome.kind == wrapper.SUCCESS
            and spec.downstream is not None
            and not outcome.skip_downstream
            and self._running
        ):
            downstream = spec.downstream
            downstream.args = (outcome.retval,)
            try:
                self._submit_nowait(downstream)
            except Exception:
                logger.exception(f'Failed to enqueue downstream job for {task_id}')

    # ---------------------------------------------------------------- control

    async def cancel(self, task_id: str) -> str:
        """Cancel a queued or running job.

        Returns 'dequeued' (was queued — removed), 'signalled' (running thread
        job — cancel event set), 'terminated' (running ML child — will be
        SIGTERM'd), or 'unknown' (not held by the orchestrator; callers treat
        this as already finished).
        """
        handle = self._handles.get(task_id)
        if handle is None:
            return 'unknown'
        if handle.state == 'QUEUED':
            lane = self._lanes.get(handle.lane)
            entry = lane.remove(task_id) if lane else None
            if entry is not None:
                self._handles.pop(task_id, None)
                self._set_result(task_id, 'REVOKED')
                return 'dequeued'
        handle.cancel_event.set()
        if handle.child_process is not None:
            return 'terminated'
        return 'signalled'

    def set_lane_concurrency(self, widths: dict[str, int]) -> None:
        """Retarget lane widths live. Unknown lane names are ignored.

        Event-loop thread only, like every other queue mutation — the settings
        router is async, so it already runs there.
        """
        if not self._running:
            return
        for name, value in widths.items():
            lane = self._lanes.get(name)
            if lane is None:
                continue
            if lane.concurrency != value:
                logger.info(f'Lane {name} concurrency {lane.concurrency} → {value}')
            lane.set_concurrency(value)

    def queued_count(self, lane_name: str) -> int:
        """Number of jobs waiting (not running) in a lane.

        Safe to call from a lane thread: a plain len() on a list the event loop
        mutates is an approximation, which is all a backpressure threshold needs.
        """
        lane = self._lanes.get(lane_name)
        return len(lane.entries) if lane else 0

    async def prioritize(self, task_id: str) -> bool:
        """Move a queued job to the front of its lane (priority 0, sequence 0).

        The task_id does not change.
        """
        handle = self._handles.get(task_id)
        if handle is None or handle.state != 'QUEUED':
            return False
        lane = self._lanes.get(handle.lane)
        return bool(lane and lane.reprioritize(task_id))

    async def get_status(self, task_id: str) -> str:
        """Job state string for any task id.

        In-memory registry first (covers untracked jobs like add-subscription),
        then TaskRecord, then 'PENDING' for unknown ids (clients keep polling
        until a terminal state).
        """
        self._sweep_results()
        entry = self._results.get(task_id)
        if entry is not None:
            return entry.state
        record = await tr_repo.get_task_by_task_id(task_id)
        if record is not None:
            return map_task_status_to_state(record.status)
        return 'PENDING'

    def get_result_registry_owner(self, task_id: str) -> tuple[bool, int | None]:
        """(known, owner) for an id in the in-memory registry.

        Untracked jobs have no TaskRecord, so this is the only way to attribute
        one. `known` distinguishes an unowned job from an id we've never seen —
        an unknown id must stay indistinguishable to every caller.
        """
        self._sweep_results()
        entry = self._results.get(task_id)
        return (entry is not None, entry.user_id if entry else None)

    def active_task_ids(self) -> set[str]:
        """Task ids the orchestrator is holding, queued or running.

        Read on the event-loop thread only — that is where _handles is mutated.
        The stranded-record sweep uses this as its liveness truth, so a row in a
        running status whose id is absent here has no job behind it.
        """
        return set(self._handles)

    def runtime_snapshot(self) -> dict:
        """Admin observability: live lanes + queued/running jobs."""
        return {
            'running': self._running,
            'lanes': {name: lane.snapshot() for name, lane in self._lanes.items()},
            'cached_results': len(self._results),
        }

    # ---------------------------------------------------------------- results

    def _set_result(self, task_id: str, state: str, user_id: int | None = None) -> None:
        if user_id is None:
            # Only submit() knows the owner; later state transitions must not drop it.
            existing = self._results.get(task_id)
            user_id = existing.user_id if existing else None
        self._results[task_id] = _ResultEntry(
            state=state,
            updated=time.monotonic(),
            terminal=state in _TERMINAL_STATES,
            user_id=user_id,
        )

    def _sweep_results(self) -> None:
        now = time.monotonic()
        expired = [
            task_id
            for task_id, entry in self._results.items()
            if (entry.terminal and now - entry.updated > RESULT_TTL_SECONDS)
            or now - entry.updated > RESULT_MAX_AGE_SECONDS
        ]
        for task_id in expired:
            del self._results[task_id]


# The process-wide orchestrator instance. Import-safe and inert: submitting
# before start() raises OrchestratorNotRunningError.
orch = Orchestrator()
