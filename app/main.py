"""FastAPI app — giao diện web chạy local để cắt video và chèn B-roll."""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import service
from app.config import (
    ANALYSIS_MODEL,
    UPLOAD_DIR,
    BrollSettings,
    CutSettings,
    RenderSettings,
    ffmpeg_available,
    has_claude,
    nvenc_available,
)
from app.jobs import manager
from app.models import AnalyzeRequest, BrollSearchRequest, RenderRequest
from app.pipeline import analyze as analyzer
from app.pipeline import broll as broll_mod
from app.pipeline import ffmpeg_utils

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".flv"}

app = FastAPI(title="Trợ lý cắt video", version="1.0")


# ---------------------------------------------------------------------------
# Trạng thái hệ thống
# ---------------------------------------------------------------------------


@app.get("/api/status")
def status() -> dict:
    return {
        "ffmpeg": ffmpeg_available(),
        "nvenc": nvenc_available(),
        "claude": has_claude(),
        "model": ANALYSIS_MODEL,
        "stock": broll_mod.stock_available(),
    }


# ---------------------------------------------------------------------------
# Tải video lên
# ---------------------------------------------------------------------------


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    if not ffmpeg_available():
        raise HTTPException(500, "Chưa cài ffmpeg. Xem hướng dẫn trong README.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(400, f"Định dạng {suffix or '(không rõ)'} chưa hỗ trợ.")

    upload_id = uuid.uuid4().hex[:12]
    dest = UPLOAD_DIR / f"{upload_id}{suffix}"
    try:
        with open(dest, "wb") as fh:
            shutil.copyfileobj(file.file, fh, length=1 << 20)
    finally:
        await file.close()

    try:
        probe = ffmpeg_utils.probe(dest)
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Không đọc được video: {exc}") from exc

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "path": str(dest),
        "probe": probe,
    }


def _find_upload(upload_id: str) -> Path:
    for p in UPLOAD_DIR.glob(f"{upload_id}.*"):
        return p
    raise HTTPException(404, "Không tìm thấy file đã tải lên. Hãy tải lại.")


# ---------------------------------------------------------------------------
# Phân tích
# ---------------------------------------------------------------------------


@app.post("/api/analyze")
def start_analysis(req: AnalyzeRequest) -> dict:
    video_path = _find_upload(req.upload_id)
    cut_settings = CutSettings.from_dict(req.cut)
    broll_settings = BrollSettings.from_dict(req.broll)

    if cut_settings.detect_offtopic and not has_claude():
        cut_settings.detect_offtopic = False

    job = manager.create("analyze")
    manager.run(
        job,
        lambda j: service.run_analysis(j, video_path, cut_settings, broll_settings, req.language),
    )
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ.")
    return job.to_dict()


# ---------------------------------------------------------------------------
# Dự án (kết quả phân tích để duyệt)
# ---------------------------------------------------------------------------


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    project = service.load_project(project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án.")
    # Bỏ bớt dữ liệu nặng không cần cho giao diện
    slim = dict(project)
    slim.pop("face_track", None)
    for b in slim.get("brolls", []):
        b.pop("candidates", None)
    return slim


@app.get("/api/projects/{project_id}/video")
def project_video(project_id: str):
    project = service.load_project(project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án.")
    path = Path(project["video_path"])
    if not path.exists():
        raise HTTPException(404, "File gốc đã bị xoá.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/projects/{project_id}/media/{sub_path:path}")
def project_media(project_id: str, sub_path: str):
    base = manager.job_dir(project_id).resolve()
    target = (base / sub_path).resolve()
    if not str(target).startswith(str(base)) or not target.exists():
        raise HTTPException(404, "Không tìm thấy file.")
    return FileResponse(target)


@app.get("/api/projects/{project_id}/output/{name}")
def project_output(project_id: str, name: str):
    base = (manager.job_dir(project_id) / "output").resolve()
    target = (base / Path(name).name).resolve()
    if not str(target).startswith(str(base)) or not target.exists():
        raise HTTPException(404, "Chưa có file này. Hãy render trước.")
    return FileResponse(target, filename=target.name)


# ---------------------------------------------------------------------------
# Đổi B-roll cho một vị trí
# ---------------------------------------------------------------------------


@app.post("/api/projects/{project_id}/brolls/{broll_id}/search")
def research_broll(project_id: str, broll_id: str, req: BrollSearchRequest) -> dict:
    project = service.load_project(project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án.")
    if not broll_mod.stock_available():
        raise HTTPException(400, "Chưa có PEXELS_API_KEY / PIXABAY_API_KEY trong file .env.")

    item = next((b for b in project.get("brolls", []) if b["id"] == broll_id), None)
    if not item:
        raise HTTPException(404, "Không tìm thấy vị trí B-roll này.")

    query = req.query.strip()
    if not query:
        raise HTTPException(400, "Từ khoá tìm kiếm đang trống.")

    candidates = broll_mod.search_candidates(query, limit=6)
    if not candidates:
        raise HTTPException(404, f"Không tìm thấy clip nào cho “{query}”.")

    line = req.line or item.get("line", "")
    ranked = analyzer.rank_broll_candidates(line, query, candidates)
    chosen = candidates[max(ranked["best_index"], 0)]
    local = broll_mod.download_candidate(chosen)
    if not local:
        raise HTTPException(502, "Tải clip về thất bại. Thử lại hoặc đổi từ khoá.")

    work = manager.job_dir(project_id)
    rel_thumb = f"broll_thumbs/{broll_id}_{chosen['id']}.jpg"
    ffmpeg_utils.make_thumbnail(local, work / rel_thumb, at=0.5, width=320)

    item.update({
        "query": query,
        "reason": ranked.get("reason", ""),
        "score": ranked.get("score", 0),
        "provider": chosen["provider"],
        "credit": chosen.get("credit", ""),
        "page": chosen.get("page", ""),
        "local_path": str(local),
        "thumb": rel_thumb,
        "enabled": True,
    })
    service.save_project(project_id, project)

    slim = {k: v for k, v in item.items() if k != "candidates"}
    return slim


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@app.post("/api/render")
def start_render(req: RenderRequest) -> dict:
    project = service.load_project(req.project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án.")

    cut_settings = CutSettings.from_dict(req.cut or project.get("settings", {}).get("cut"))
    render_settings = RenderSettings.from_dict(req.render)

    cuts = req.cuts or project.get("cuts", [])
    brolls = req.brolls or project.get("brolls", [])

    # Frontend chỉ gửi id + enabled cho B-roll; ghép lại với dữ liệu đầy đủ trên server
    by_id = {b["id"]: b for b in project.get("brolls", [])}
    merged: list[dict] = []
    for b in brolls:
        full = dict(by_id.get(b.get("id"), {}))
        full.update({k: v for k, v in b.items() if v is not None})
        if full.get("local_path"):
            merged.append(full)

    job = manager.create("render")
    manager.run(
        job,
        lambda j: service.run_render(j, project, cuts, merged, cut_settings, render_settings),
    )
    return {"job_id": job.id}


# ---------------------------------------------------------------------------
# Giao diện
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    log.exception("Lỗi không bắt được")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
