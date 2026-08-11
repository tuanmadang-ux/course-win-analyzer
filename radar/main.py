"""FastAPI app — Radar đối thủ, chạy local trên máy bạn."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from radar import measure, publish, service, store
from radar.config import (
    BRAND_NAME,
    FORMAT_LABELS,
    IMPORT_DIR,
    WRITER_MODEL,
    MineSettings,
    WriteSettings,
    has_apify,
    has_claude,
    has_page,
)
from radar.ingest import apify
from radar.jobs import manager
from radar.mine.insight import KIND_LABELS
from radar.models import (
    CollectRequest,
    DraftUpdate,
    MineRequest,
    PasteRequest,
    ScheduleRequest,
    SourceRequest,
    WriteRequest,
)
from radar.publish import schedule as scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("radar")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_IMPORT = {".json", ".jsonl", ".csv", ".tsv"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

app = FastAPI(title="Radar đối thủ", version="1.0")
store.init_db()


# ---------------------------------------------------------------------------
# Trạng thái
# ---------------------------------------------------------------------------


@app.get("/api/status")
def status() -> dict:
    return {
        "claude": has_claude(),
        "model": WRITER_MODEL,
        "apify": {**apify.available(), "ready": has_apify()},
        "page": has_page(),
        "brand": BRAND_NAME,
        "formats": FORMAT_LABELS,
        "kinds": KIND_LABELS,
    }


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ.")
    return job.to_dict()


# ---------------------------------------------------------------------------
# Nguồn theo dõi
# ---------------------------------------------------------------------------


@app.get("/api/sources")
def get_sources() -> list[dict]:
    return store.list_sources()


@app.post("/api/sources")
def create_source(req: SourceRequest) -> dict:
    if not req.name.strip():
        raise HTTPException(400, "Chưa đặt tên cho nguồn.")
    return store.add_source(req.name, req.ref, req.platform, req.note)


@app.delete("/api/sources/{source_id}")
def remove_source(source_id: str) -> dict:
    store.delete_source(source_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Bước 1 — thu thập
# ---------------------------------------------------------------------------


@app.post("/api/paste")
def paste_post(req: PasteRequest) -> dict:
    if not store.get_source(req.source_id):
        raise HTTPException(404, "Không tìm thấy nguồn. Tạo nguồn trước đã.")
    if not req.post_text.strip():
        raise HTTPException(400, "Chưa dán nội dung bài.")
    return service.run_paste(req)


@app.post("/api/upload")
async def upload_import(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_IMPORT:
        raise HTTPException(400, f"Chỉ nhận {', '.join(sorted(ALLOWED_IMPORT))}.")

    token = uuid.uuid4().hex[:12]
    dest = IMPORT_DIR / f"{token}{suffix}"
    try:
        with open(dest, "wb") as fh:
            shutil.copyfileobj(file.file, fh, length=1 << 20)
    finally:
        await file.close()
    return {"token": token, "filename": file.filename, "size": dest.stat().st_size}


def _import_path(token: str) -> Path:
    """Chỉ nhận token do máy sinh, và chỉ tìm trong đúng thư mục nhập."""
    if not SAFE_NAME.match(token or ""):
        raise HTTPException(400, "Mã file không hợp lệ.")
    for path in IMPORT_DIR.glob(f"{token}.*"):
        return path
    raise HTTPException(404, "Không tìm thấy file đã tải lên. Hãy tải lại.")


@app.post("/api/collect")
def collect(req: CollectRequest) -> dict:
    if not store.get_source(req.source_id):
        raise HTTPException(404, "Không tìm thấy nguồn.")

    upload_path = None
    if req.adapter == "file":
        upload_path = _import_path(req.target)
    elif not has_apify():
        raise HTTPException(
            400,
            "Chưa có APIFY_TOKEN trong .env. Bạn vẫn dùng được hai cách kia: "
            "dán tay, hoặc nhập file CSV/JSON đã xuất sẵn.",
        )
    elif not req.target.strip():
        raise HTTPException(400, "Chưa nhập link fanpage cần quét.")

    job = manager.create("collect")
    manager.run(job, lambda j: service.run_collect(j, req, upload_path))
    return {"job_id": job.id}


@app.get("/api/posts")
def get_posts(source_id: str | None = None, limit: int = 100) -> list[dict]:
    posts = store.list_posts(source_id, limit)
    for p in posts:
        p["stored_comments"] = store.comment_count(p["id"])
        p["text"] = (p.get("text") or "")[:400]
    return posts


@app.post("/api/mine")
def mine_posts(req: MineRequest) -> dict:
    if not req.post_ids:
        raise HTTPException(400, "Chưa chọn bài nào để đào.")
    settings = MineSettings.from_dict(req.mine)
    job = manager.create("mine")
    manager.run(job, lambda j: service.run_mine(j, req.post_ids, settings))
    return {"job_id": job.id}


# ---------------------------------------------------------------------------
# Bước 2 — insight & viết bài
# ---------------------------------------------------------------------------


@app.get("/api/insights")
def get_insights(status: str | None = "new", post_id: str | None = None) -> list[dict]:
    return store.list_insights(post_id=post_id, status=status or None)


@app.post("/api/insights/{insight_id}/ignore")
def ignore_insight(insight_id: str) -> dict:
    store.set_insight_status(insight_id, "ignored")
    return {"ok": True}


@app.post("/api/write")
def write(req: WriteRequest) -> dict:
    if not req.insight_ids:
        raise HTTPException(400, "Chưa chọn insight nào.")
    settings = WriteSettings.from_dict(req.write)
    job = manager.create("write")
    manager.run(job, lambda j: service.run_write(j, req.insight_ids, settings))
    return {"job_id": job.id}


# ---------------------------------------------------------------------------
# Bước 3 — duyệt & đăng
# ---------------------------------------------------------------------------


@app.get("/api/drafts")
def get_drafts(status: str | None = None) -> list[dict]:
    return store.list_drafts(status)


@app.get("/api/drafts/{draft_id}")
def get_draft(draft_id: str) -> dict:
    draft = store.get_draft(draft_id)
    if not draft:
        raise HTTPException(404, "Không tìm thấy bài.")
    return draft


@app.patch("/api/drafts/{draft_id}")
def edit_draft(draft_id: str, req: DraftUpdate) -> dict:
    if not store.get_draft(draft_id):
        raise HTTPException(404, "Không tìm thấy bài.")

    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if fields:
        store.update_draft(draft_id, **fields)
    # Sửa chữ xong thì đo lại độ trùng lặp ngay, cảnh báo cũ không được đọng lại
    updated = service.recheck_draft(draft_id)
    if updated and updated.get("warnings") and updated.get("status") == "approved":
        updated = store.update_draft(draft_id, status="draft")
    return updated or {}


@app.delete("/api/drafts/{draft_id}")
def remove_draft(draft_id: str) -> dict:
    store.delete_draft(draft_id)
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: str) -> dict:
    try:
        return publish.approve(draft_id)
    except publish.PublishBlocked as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: str) -> dict:
    return publish.reject(draft_id)


@app.post("/api/schedule")
def schedule_draft(req: ScheduleRequest) -> dict:
    try:
        if req.publish_now:
            return publish.publish_now(req.draft_id)
        return publish.plan(req.draft_id, req.scheduled_at)
    except publish.PublishBlocked as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - lỗi Graph API trả thẳng cho người dùng đọc
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/schedule/golden")
def golden() -> dict:
    info = scheduler.golden_hours()
    suggestion = scheduler.next_slot([
        d["scheduled_at"] for d in store.list_drafts()
        if d.get("scheduled_at") and d["status"] in ("scheduled", "published")
    ])
    return {
        **info,
        "next_slot": suggestion,
        "next_slot_label": scheduler.describe(suggestion),
    }


@app.get("/api/due")
def due() -> list[dict]:
    return publish.due_now()


# ---------------------------------------------------------------------------
# Bước 4 — đo lường
# ---------------------------------------------------------------------------


@app.post("/api/measure/refresh")
def refresh_metrics() -> dict:
    job = manager.create("measure")
    manager.run(job, lambda _j: measure.refresh())
    return {"job_id": job.id}


@app.get("/api/report")
def report() -> dict:
    return measure.report()


# ---------------------------------------------------------------------------
# Giao diện
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    log.exception("Lỗi không bắt được")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
