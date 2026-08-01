"""FastAPI — bảng điều khiển render cho xưởng shorts faceless (chạy local)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from webapp import catalog
from webapp.config import (
    OUT_DIR,
    PORT,
    QA_DIR,
    deps_installed,
    ffmpeg_available,
    find_browser,
    node_available,
)
from webapp.jobs import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("webapp")

STATIC_DIR = Path(__file__).parent / "static"

# Composition id do Remotion sinh ra — chỉ chữ và số. Chặn mọi thứ khác trước khi
# ghép vào đường dẫn file hoặc đưa xuống dòng lệnh.
SAFE_ID = re.compile(r"^[A-Za-z0-9]+$")

app = FastAPI(title="Xưởng Shorts — bảng điều khiển render", version="1.0")


def _valid_shot(comp_id: str) -> dict:
    if not SAFE_ID.match(comp_id):
        raise HTTPException(400, "composition id không hợp lệ")
    shot = catalog.shot(comp_id)
    if not shot:
        raise HTTPException(404, f"không có composition '{comp_id}'")
    return shot


# ---------------------------------------------------------------------------
# Trạng thái + danh mục
# ---------------------------------------------------------------------------


@app.get("/api/status")
def status() -> dict:
    browser = find_browser()
    return {
        "node": node_available(),
        "ffmpeg": ffmpeg_available(),
        "deps": deps_installed(),
        "browser": browser,
        "browser_auto": browser is None,
        "shots": len(catalog.shots()),
    }


@app.get("/api/shots")
def list_shots() -> dict:
    return {"shots": catalog.shots()}


@app.get("/api/shots/{comp_id}/script")
def shot_script(comp_id: str) -> dict:
    _valid_shot(comp_id)
    text = catalog.script_text(comp_id)
    if text is None:
        raise HTTPException(404, "shot này không có script.md")
    return {"id": comp_id, "script": text}


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


class RenderRequest(BaseModel):
    id: str
    kind: str = Field(default="still", pattern="^(still|video)$")
    scale: float = Field(default=1.0, ge=0.25, le=2.0)


class FramesRequest(BaseModel):
    id: str
    frames: str = "0"
    scale: float = Field(default=0.5, ge=0.25, le=2.0)


@app.post("/api/render")
def render(req: RenderRequest) -> dict:
    _valid_shot(req.id)
    argv = ["node", "scripts/render-all.mjs", req.id, f"--scale={req.scale}"]
    if req.kind == "still":
        argv.append("--still")
    job = manager.start(req.kind, argv, shot=req.id)
    return job.to_dict()


@app.post("/api/frames")
def frames(req: FramesRequest) -> dict:
    """Render vài khung hình để soi nhanh (QA) — nhanh hơn render cả video."""
    _valid_shot(req.id)
    nums = [n.strip() for n in req.frames.split(",") if n.strip()]
    if not nums or not all(n.isdigit() for n in nums):
        raise HTTPException(400, "danh sách khung hình phải là các số, cách nhau bởi dấu phẩy")
    if len(nums) > 12:
        raise HTTPException(400, "tối đa 12 khung hình một lần")
    argv = ["node", "scripts/frames.mjs", req.id, ",".join(nums), f"--scale={req.scale}"]
    job = manager.start("frames", argv, shot=req.id)
    return job.to_dict()


@app.post("/api/gen")
def regenerate_registry() -> dict:
    """Chạy lại npm run gen — cần sau khi thêm/đổi tên shot."""
    return manager.start("gen", ["node", "scripts/gen-registry.mjs"]).to_dict()


# ---------------------------------------------------------------------------
# Tác vụ
# ---------------------------------------------------------------------------


@app.get("/api/jobs")
def jobs() -> dict:
    return {"jobs": manager.all()}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "không có tác vụ này")
    return {**job.to_dict(), "log": manager.logs(job_id)[-40:]}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    if not manager.cancel(job_id):
        raise HTTPException(409, "tác vụ đã kết thúc hoặc không huỷ được")
    return {"ok": True}


# ---------------------------------------------------------------------------
# File đã render
# ---------------------------------------------------------------------------


@app.get("/api/still/{comp_id}.png")
def still(comp_id: str) -> FileResponse:
    _valid_shot(comp_id)
    path = OUT_DIR / f"{comp_id}.png"
    if not path.exists():
        raise HTTPException(404, "chưa có ảnh preview — bấm 'Ảnh preview' để render")
    return FileResponse(path, media_type="image/png")


@app.get("/api/qa/{name}")
def qa_frame(name: str) -> FileResponse:
    if not re.match(r"^[A-Za-z0-9_-]+\.png$", name):
        raise HTTPException(400, "tên file không hợp lệ")
    path = QA_DIR / name
    if not path.exists():
        raise HTTPException(404, "không có khung hình này")
    return FileResponse(path, media_type="image/png")


@app.get("/api/qa-frames/{comp_id}")
def qa_frames(comp_id: str) -> dict:
    _valid_shot(comp_id)
    if not QA_DIR.is_dir():
        return {"frames": []}
    names = sorted(p.name for p in QA_DIR.glob(f"{comp_id}-f*.png"))
    return {"frames": names}


@app.get("/api/video/{comp_id}")
def video(comp_id: str) -> FileResponse:
    shot = _valid_shot(comp_id)
    ext = "mov" if shot["transparent"] else "mp4"
    path = OUT_DIR / f"{comp_id}.{ext}"
    if not path.exists():
        raise HTTPException(404, "chưa render video này")
    return FileResponse(
        path,
        media_type="video/quicktime" if ext == "mov" else "video/mp4",
        filename=f"{comp_id}.{ext}",
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
