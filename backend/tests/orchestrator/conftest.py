"""Shared fixtures for orchestrator tests."""

import pytest

from orchestrator import jobs
from orchestrator.core import Orchestrator
from orchestrator.jobs import DEFAULT_LANE


@pytest.fixture
def job_registry():
    """Isolated job registry per test (restored afterwards)."""
    saved = dict(jobs.JOB_REGISTRY)
    jobs.JOB_REGISTRY.clear()
    yield jobs.JOB_REGISTRY
    jobs.JOB_REGISTRY.clear()
    jobs.JOB_REGISTRY.update(saved)


@pytest.fixture
async def orch_instance(job_registry):
    """A started orchestrator (default lane concurrency 2), stopped on teardown."""
    o = Orchestrator()
    await o.start({DEFAULT_LANE: 2})
    yield o
    await o.stop(job_grace=2.0)
