"""Quản lý tác vụ chạy nền + báo tiến độ cho giao diện web."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.config import JOB_DIR

log = logging.getLogger(__name__)

# Id do máy sinh: hex/uuid. Bất cứ thứ gì khác đều là bịa.
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class Job:
    id: str
    kind: str                       # "analyze" | "render"
    status: str = "queued"          # queued | running | done | error
    stage: str = ""
    progress: float = 0.0           # 0..1
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

    # -- vòng đời ----------------------------------------------------------

    def create(self, kind: str, job_id: str | None = None) -> Job:
        job = Job(id=job_id or uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job:
            return job
        return self._load_from_disk(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:50]]

    # -- cập nhật ----------------------------------------------------------

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

    # -- chạy nền ----------------------------------------------------------

    def run(self, job: Job, fn: Callable[[Job], dict]) -> None:
        def _worker() -> None:
            self.update(job.id, status="running", stage="Bắt đầu", progress=0.01)
            try:
                result = fn(job)
                self.update(
                    job.id, status="done", progress=1.0,
                    stage="Hoàn tất", message="", result=result or {},
                )
                self.persist(job.id)
            except Exception as exc:  # noqa: BLE001
                log.error("Job %s lỗi: %s\n%s", job.id, exc, traceback.format_exc())
                self.update(job.id, status="error", error=str(exc), stage="Lỗi")

        threading.Thread(target=_worker, name=f"job-{job.id}", daemon=True).start()

    # -- lưu / nạp ---------------------------------------------------------

    def job_dir(self, job_id: str) -> Path:
        """Thư mục làm việc của một job/dự án.

        Đây là nơi duy nhất sinh đường dẫn từ id, nên cũng là nơi chặn id bịa
        kiểu `../../etc` — id thật luôn là chuỗi hex do máy sinh ra.
        """
        if not SAFE_ID.match(job_id or ""):
            raise ValueError(f"Mã dự án không hợp lệ: {job_id!r}")
        d = JOB_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def persist(self, job_id: str) -> None:
        job = self.get(job_id)
        if not job:
            return
        path = self.job_dir(job_id) / "job.json"
        path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_from_disk(self, job_id: str) -> Job | None:
        path = JOB_DIR / job_id / "job.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            job = Job(**data)
            with self._lock:
                self._jobs[job.id] = job
            return job
        except Exception:  # noqa: BLE001
            return None


manager = JobManager()
