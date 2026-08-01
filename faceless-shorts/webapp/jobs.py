"""Chạy render dưới tiến trình con, báo tiến độ về giao diện."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from webapp.config import REMOTION_DIR, render_env

log = logging.getLogger(__name__)

# render-all.mjs in "  <id>: 42%" (dùng \r nên phải bắt trên cả dòng gộp). Phải neo
# vào đúng dạng "<id>: <số>%" rồi đối chiếu <id> với shot đang render — bắt mỗi "%"
# trên dòng là dính nhầm cả "Downloading 50% of chrome" lẫn "Error: 100% ...".
_PROGRESS_RE = re.compile(r"^\s*(\S+):\s+(\d{1,3})%")
# frames.mjs / render-all.mjs in "  -> out/x.png" hoặc "  still -> out/x.png".
_WROTE_RE = re.compile(r"->\s*(\S+)")

MAX_LOG_LINES = 400
# Giữ lại bấy nhiêu tác vụ đã kết thúc; cũ hơn thì dọn để phiên chạy dài không phình.
MAX_FINISHED_JOBS = 60


@dataclass
class Job:
    id: str
    kind: str                        # "video" | "still" | "frames" | "gen"
    shot: str = ""
    status: str = "queued"           # queued | running | done | error
    progress: float = 0.0            # 0..1
    message: str = ""
    error: str = ""
    outputs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["elapsed_s"] = round((self.updated_at or time.time()) - self.created_at, 1)
        return d


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._logs: dict[str, list[str]] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    # -- truy vấn ----------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def logs(self, job_id: str) -> list[str]:
        with self._lock:
            return list(self._logs.get(job_id, []))

    def active(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self._jobs.values() if j.status in ("queued", "running")]

    def all(self) -> list[dict]:
        with self._lock:
            js = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in js[:40]]

    # -- điều khiển --------------------------------------------------------

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            proc = self._procs.get(job_id)
            job = self._jobs.get(job_id)
        if not proc or not job or job.status not in ("queued", "running"):
            return False
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._update(job_id, status="error", error="đã huỷ theo yêu cầu")
        return True

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated_at = time.time()

    def _append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            buf = self._logs.setdefault(job_id, [])
            buf.append(line)
            if len(buf) > MAX_LOG_LINES:
                del buf[: len(buf) - MAX_LOG_LINES]

    # -- chạy --------------------------------------------------------------

    def busy_with(self, shot: str, kind: str) -> Job | None:
        """Tác vụ đang chạy ghi đúng file mà (shot, kind) này sắp ghi, nếu có."""
        with self._lock:
            return next(
                (
                    j
                    for j in self._jobs.values()
                    if j.shot == shot and j.kind == kind and j.status in ("queued", "running")
                ),
                None,
            )

    def _prune(self) -> None:
        """Bỏ bớt tác vụ đã kết thúc, giữ lại MAX_FINISHED_JOBS cái mới nhất."""
        finished = sorted(
            (j for j in self._jobs.values() if j.status in ("done", "error")),
            key=lambda j: j.updated_at,
        )
        for job in finished[: max(0, len(finished) - MAX_FINISHED_JOBS)]:
            self._jobs.pop(job.id, None)
            self._logs.pop(job.id, None)

    def start(self, kind: str, argv: list[str], shot: str = "") -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, shot=shot)
        with self._lock:
            self._jobs[job.id] = job
            self._logs[job.id] = []
            self._prune()
        threading.Thread(target=self._run, args=(job.id, argv), daemon=True).start()
        return job

    def _run(self, job_id: str, argv: list[str]) -> None:
        self._update(job_id, status="running", message="đang khởi động…")
        log.info("job %s: %s", job_id, " ".join(argv))
        try:
            proc = subprocess.Popen(
                argv,
                cwd=REMOTION_DIR,
                env=render_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                errors="replace",
            )
        except OSError as e:
            self._update(job_id, status="error", error=f"không chạy được: {e}")
            return

        with self._lock:
            self._procs[job_id] = proc

        outputs: list[str] = []
        job = self.get(job_id)
        expect = job.shot if job else ""
        assert proc.stdout is not None
        for raw in proc.stdout:
            # Remotion ghi đè tiến độ bằng \r — tách ra để không nuốt mất dòng.
            for line in raw.replace("\r", "\n").split("\n"):
                line = line.rstrip()
                if not line:
                    continue
                self._append_log(job_id, line)

                m = _PROGRESS_RE.match(line)
                if m and expect and m.group(1) == expect:
                    pct = min(100, int(m.group(2)))
                    self._update(job_id, progress=pct / 100.0, message=line.strip())
                elif (m := _WROTE_RE.search(line)) and ("->" in line):
                    outputs.append(m.group(1))
                    self._update(job_id, outputs=list(outputs), message=line.strip())
                elif line.startswith("bundling"):
                    self._update(job_id, message="đang bundle…")

        code = proc.wait()
        with self._lock:
            self._procs.pop(job_id, None)

        current = self.get(job_id)
        if current and current.status == "error":
            return  # đã bị huỷ

        if code == 0:
            self._update(
                job_id,
                status="done",
                progress=1.0,
                outputs=outputs,
                message=f"xong — {len(outputs)} file" if outputs else "xong",
            )
        else:
            tail = " | ".join(self.logs(job_id)[-4:])
            self._update(job_id, status="error", error=f"thoát mã {code}. {tail}"[:600])


manager = JobManager()
