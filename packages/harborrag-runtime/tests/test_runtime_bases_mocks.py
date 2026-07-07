from __future__ import annotations

import pytest
from harborrag_runtime.composition import CompositionRoot
from harborrag_runtime.job_state import InMemoryJobStore, JobState
from harborrag_runtime.jobs.base import BaseJobStore
from harborrag_runtime.jobs.mock import MockJobStore
from harborrag_runtime.local import run_sync
from harborrag_runtime.schedules import ScheduleSpec
from harborrag_runtime.scheduling.base import BaseScheduler
from harborrag_runtime.scheduling.mock import MockScheduler
from harborrag_runtime.services.base import BaseRuntimeService
from harborrag_runtime.services.mock import MockRuntimeService
from harborrag_runtime.supervision.base import BaseSupervisor
from harborrag_runtime.supervision.mock import MockSupervisor


class BrokenJobStore(BaseJobStore):
    def save(self, job):
        return super().save(job)

    def get(self, job_id):
        return super().get(job_id)


class BrokenScheduler(BaseScheduler):
    def add(self, schedule):
        return super().add(schedule)


class BrokenSupervisor(BaseSupervisor):
    def submit(self, job_id):
        return super().submit(job_id)


class BrokenRuntimeService(BaseRuntimeService):
    def diagnostics(self):
        return super().diagnostics()

    def run_mock_ingestion(self):
        return super().run_mock_ingestion()


def test_runtime_base_methods_raise():
    with pytest.raises(NotImplementedError):
        BrokenJobStore().save(JobState("j"))
    with pytest.raises(NotImplementedError):
        BrokenJobStore().get("j")
    with pytest.raises(NotImplementedError):
        BrokenScheduler().add(ScheduleSpec("daily", "0 0 * * *"))
    with pytest.raises(NotImplementedError):
        BrokenSupervisor().submit("job")
    with pytest.raises(NotImplementedError):
        BrokenRuntimeService().diagnostics()
    with pytest.raises(NotImplementedError):
        BrokenRuntimeService().run_mock_ingestion()


def test_runtime_mocks_and_composition():
    job = JobState("job-1")
    store = MockJobStore()
    store.save(job)
    assert store.get("job-1") is job
    in_memory = InMemoryJobStore()
    in_memory.save(job)
    assert in_memory.get("job-1") is job
    assert in_memory.get("missing") is None
    scheduler = MockScheduler()
    scheduler.add(ScheduleSpec("hourly", "0 * * * *"))
    assert scheduler.schedules[0].name == "hourly"
    supervisor = MockSupervisor()
    supervisor.submit("job-1")
    assert supervisor.submitted == ["job-1"]
    assert run_sync(lambda: 42) == 42
    root = CompositionRoot.local()
    assert root.diagnostics()["runtime"]["provider"] == "mock_runtime"
    docs = root.mock_pipeline().run_once()
    assert docs
    service = MockRuntimeService()
    assert service.diagnostics()["ready"] is True
    assert service.run_mock_ingestion()["documents"]
