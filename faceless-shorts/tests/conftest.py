"""Fixture dùng chung cho bộ test webapp."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAKE_RENDER = Path(__file__).parent / "fake_render.py"


@pytest.fixture
def fresh_manager():
    """JobManager sạch — không dùng chung state giữa các test."""
    from webapp.jobs import JobManager

    return JobManager()


@pytest.fixture
def fake_argv():
    """Dựng argv chạy fake_render.py thay cho Remotion thật."""

    def build(comp: str = "FakeShot", *flags: str) -> list[str]:
        return [sys.executable, str(FAKE_RENDER), comp, *flags]

    return build


@pytest.fixture
def client(monkeypatch):
    """TestClient với manager đã bị chặn — không cho spawn tiến trình thật.

    Mọi lệnh render trong test API chỉ ghi lại lời gọi; phần chạy tiến trình
    thật do test_jobs.py lo, dùng fake_render.py.
    """
    from fastapi.testclient import TestClient

    from webapp import jobs, main

    started: list[dict] = []

    def fake_start(kind: str, argv: list[str], shot: str = "") -> jobs.Job:
        job = jobs.Job(id=f"test{len(started):04d}", kind=kind, shot=shot, status="running")
        started.append({"kind": kind, "argv": argv, "shot": shot})
        main.manager._jobs[job.id] = job
        return job

    monkeypatch.setattr(main.manager, "start", fake_start)
    main.manager._jobs.clear()
    main.manager._logs.clear()

    c = TestClient(main.app)
    c.started = started  # type: ignore[attr-defined]
    yield c
    main.manager._jobs.clear()
    main.manager._logs.clear()
