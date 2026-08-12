"""Tác vụ chạy nền + báo tiến độ. Giữ trong bộ nhớ; dữ liệu thật nằm ở SQLite."""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    kind: str                       # collect | mine | write | publish | measure
    status: str = "queued"          # queued | running | done | error
    stage: str = ""
    progress: float = 0.0
    message: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > 200:  # dọn job cũ, tránh phình bộ nhớ
                for old in sorted(self._jobs.values(), key=lambda j: j.created_at)[:50]:
                    self._jobs.pop(old.id, None)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in fields.items():
                if hasattr(job, k):
                    setattr(job, k, v)
            job.updated_at = time.time()

    def progress(self, job_id: str, stage: str, value: float, message: str = "") -> None:
        self.update(job_id, stage=stage, progress=max(0.0, min(1.0, value)), message=message)

    def run(self, job: Job, fn: Callable[[Job], dict]) -> None:
        def _worker() -> None:
            self.update(job.id, status="running", stage="Bắt đầu", progress=0.01)
            try:
                result = fn(job)
                self.update(job.id, status="done", progress=1.0, stage="Hoàn tất",
                            message="", result=result or {})
            except Exception as exc:  # noqa: BLE001
                log.error("Job %s lỗi: %s\n%s", job.id, exc, traceback.format_exc())
                self.update(job.id, status="error", error=str(exc), stage="Lỗi")

        threading.Thread(target=_worker, name=f"radar-{job.id}", daemon=True).start()


manager = JobManager()
