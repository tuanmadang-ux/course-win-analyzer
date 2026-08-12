"""FastAPI app — giao diện web chạy local để cắt video và chèn B-roll."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import service
from app.avatar import gemini as gemini_mod
from app.avatar import lipsync as lipsync_mod
from app.avatar import music as music_mod
from app.avatar import script as script_mod
from app.avatar import service as avatar_service
from app.config import (
    ANALYSIS_MODEL,
    GEMINI_TEXT_MODEL,
    GEMINI_TTS_MODEL,
    GEMINI_VEO_MODEL,
    UPLOAD_DIR,
    AvatarSettings,
    BrollSettings,
    CutSettings,
    RenderSettings,
    ffmpeg_available,
    has_claude,
    has_gemini,
    nvenc_available,
)
from app.jobs import manager
from app.models import (
    AnalyzeRequest,
    AvatarGenerateRequest,
    BrollSearchRequest,
    ReanalyzeRequest,
    RenderRequest,
    ScriptPreviewRequest,
)
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
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

app = FastAPI(title="Trợ lý video", version="1.1")


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
        "gemini": has_gemini(),
    }


# ---------------------------------------------------------------------------
# Tạo video người nói từ ảnh
# ---------------------------------------------------------------------------


@app.get("/api/avatar/options")
def avatar_options() -> dict:
    """Mọi thứ giao diện cần để dựng form: voice, engine, nhạc, trạng thái key."""
    return {
        "gemini": has_gemini(),
        "models": {
            "text": GEMINI_TEXT_MODEL,
            "tts": GEMINI_TTS_MODEL,
            "veo": GEMINI_VEO_MODEL,
        },
        "voices": gemini_mod.VOICES,
        "engines": lipsync_mod.describe(),
        "engine_active": _safe_engine(),
        "music": music_mod.library(),
        "styles": [
            {"id": key, "label": label}
            for key, label in script_mod.STYLE_HINTS.items()
        ],
        "defaults": AvatarSettings().__dict__,
    }


def _safe_engine() -> str:
    """Engine sẽ được dùng nếu bấm tạo ngay bây giờ — không ném lỗi ra API."""
    try:
        return lipsync_mod.resolve_engine()
    except lipsync_mod.LipSyncError:
        return "still"


@app.post("/api/avatar/photos")
async def upload_photo(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in PHOTO_EXT:
        raise HTTPException(
            400, f"Ảnh định dạng {suffix or '(không rõ)'} chưa hỗ trợ. Dùng JPG hoặc PNG."
        )

    photo_id = uuid.uuid4().hex[:12]
    dest = UPLOAD_DIR / f"{photo_id}{suffix}"
    try:
        with open(dest, "wb") as fh:
            shutil.copyfileobj(file.file, fh, length=1 << 20)
    finally:
        await file.close()

    # Báo ngay nếu ảnh không dò được mặt, đừng để tới lúc render mới biết
    from app.avatar import portrait as portrait_mod  # noqa: PLC0415

    try:
        face = portrait_mod.detect_face(dest)
    except portrait_mod.PortraitError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc

    return {
        "photo_id": photo_id,
        "filename": file.filename,
        "face_found": face is not None,
        "warning": "" if face else "Không dò được khuôn mặt — nhép môi có thể kém. Thử ảnh chính diện, rõ mặt.",
    }


def _find_photo(photo_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", photo_id or ""):
        raise HTTPException(400, "Mã ảnh không hợp lệ.")
    for p in UPLOAD_DIR.glob(f"{photo_id}.*"):
        if p.suffix.lower() in PHOTO_EXT:
            return p
    raise HTTPException(404, "Không tìm thấy ảnh đã tải lên. Hãy tải lại.")


@app.post("/api/avatar/script")
def preview_script(req: ScriptPreviewRequest) -> dict:
    """Xem trước kịch bản trước khi tốn lượt TTS và thời gian nhép môi."""
    settings = AvatarSettings.from_dict(req.avatar)
    try:
        plan = script_mod.plan(req.content, settings, max(min(req.speakers, 2), 1))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    total = sum(script_mod.estimate_seconds(s["text"]) for s in plan["segments"])
    return {**plan, "estimated_seconds": round(total, 1)}


@app.post("/api/avatar/music")
async def upload_music(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    await file.close()
    try:
        saved = music_mod.save_upload(data, file.filename or "nhac.mp3")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"name": saved.name, "duration": round(music_mod.probe_duration(saved), 1)}


@app.post("/api/avatar/generate")
def start_avatar(req: AvatarGenerateRequest) -> dict:
    if not ffmpeg_available():
        raise HTTPException(500, "Chưa cài ffmpeg. Xem hướng dẫn trong README.")
    if not req.photo_ids:
        raise HTTPException(400, "Chưa chọn ảnh nào.")
    if not (req.content or "").strip():
        raise HTTPException(400, "Chưa nhập nội dung cho video.")

    photos = [_find_photo(pid) for pid in req.photo_ids[:2]]
    settings = AvatarSettings.from_dict(req.avatar)
    render_settings = RenderSettings.from_dict(req.render)

    if settings.engine == "veo" and not has_gemini():
        raise HTTPException(400, "Chế độ Veo cần GEMINI_API_KEY trong file .env.")
    if settings.engine != "veo" and not has_gemini():
        raise HTTPException(
            400,
            "Cần GEMINI_API_KEY để đọc lời thoại thành tiếng. "
            "Lấy key miễn phí ở https://aistudio.google.com/apikey",
        )

    job = manager.create("avatar")
    manager.run(
        job,
        lambda j: avatar_service.generate(j, photos, req.content, settings, render_settings),
    )
    return {"job_id": job.id}


@app.get("/api/avatar/projects/{project_id}")
def get_avatar_project(project_id: str) -> dict:
    project = avatar_service.load_project(project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án.")
    return project


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


def _job_dir(project_id: str) -> Path:
    """Thư mục dự án, đổi id bịa thành 404 thay vì để lỗi lọt ra ngoài."""
    try:
        return manager.job_dir(project_id)
    except ValueError as exc:
        raise HTTPException(404, "Mã dự án không hợp lệ.") from exc


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


@app.post("/api/projects/{project_id}/reanalyze")
def start_reanalysis(project_id: str, req: ReanalyzeRequest) -> dict:
    """Dò lại các đoạn cắt với ngưỡng mới mà không phải bóc lời lại."""
    project = service.load_project(project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án.")

    cut_settings = CutSettings.from_dict(req.cut or project.get("settings", {}).get("cut"))
    broll_settings = BrollSettings.from_dict(req.broll or project.get("settings", {}).get("broll"))
    if cut_settings.detect_offtopic and not has_claude():
        cut_settings.detect_offtopic = False

    job = manager.create("reanalyze")
    manager.run(
        job,
        lambda j: service.run_reanalysis(j, project, cut_settings, broll_settings, req.redo_broll),
    )
    return {"job_id": job.id}


@app.get("/api/projects/{project_id}/video")
def project_video(project_id: str):
    project = service.load_project(project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án.")
    path = Path(project["video_path"])
    if not path.exists():
        raise HTTPException(404, "File gốc đã bị xoá.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


def _safe_file(base: Path, relative: str, missing_msg: str) -> Path:
    """Giải đường dẫn con và bắt buộc nó nằm TRONG `base`.

    Phải dùng is_relative_to chứ không so tiền tố chuỗi: thư mục `abc-secret`
    có tiền tố trùng với `abc`, nên so chuỗi sẽ cho đọc chéo sang dự án khác.
    """
    base = base.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404, missing_msg)
    return target


@app.get("/api/projects/{project_id}/media/{sub_path:path}")
def project_media(project_id: str, sub_path: str):
    target = _safe_file(_job_dir(project_id), sub_path, "Không tìm thấy file.")
    return FileResponse(target)


@app.get("/api/projects/{project_id}/output/{name}")
def project_output(project_id: str, name: str):
    base = _job_dir(project_id) / "output"
    target = _safe_file(base, Path(name).name, "Chưa có file này. Hãy render trước.")
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

    work = _job_dir(project_id)
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
