"""Điều phối: thu thập → đào insight → viết → duyệt → đăng → đo.

Mỗi hàm `run_*` ở đây là thân của một job chạy nền, nhận `job` để báo tiến độ.
"""

from __future__ import annotations

import logging
from pathlib import Path

from radar import create, ingest, mine, store
from radar.config import MineSettings, WriteSettings
from radar.create import originality
from radar.jobs import Job, manager
from radar.models import CollectRequest, PasteRequest

log = logging.getLogger(__name__)


def _progress(job: Job):
    def report(value: float, message: str) -> None:
        manager.progress(job.id, "Đang chạy", value, message)
    return report


# ---------------------------------------------------------------------------
# Bước 1 + 2 — thu thập rồi đào luôn
# ---------------------------------------------------------------------------


def run_collect(job: Job, req: CollectRequest, upload_path: Path | None = None) -> dict:
    settings = MineSettings.from_dict(req.mine)
    report = _progress(job)

    manager.progress(job.id, "Thu thập", 0.05, "Đang lấy bài…")
    if req.adapter == "file":
        if not upload_path:
            raise ValueError("Chưa chọn file để nhập.")
        collected = ingest.collect_from_file(req.source_id, upload_path, settings, report)
    else:
        collected = ingest.collect_from_apify(
            req.source_id, req.target, settings, req.with_comments, report
        )

    post_ids = collected["post_ids"]
    if not post_ids:
        return {**collected, "insights": 0, "message": "Không có bài nào qua được bộ lọc."}

    manager.progress(job.id, "Đào insight", 0.6, f"Đang đọc bình luận của {len(post_ids)} bài…")
    mined = mine.mine_posts(
        post_ids, settings,
        lambda v, m: manager.progress(job.id, "Đào insight", 0.6 + 0.4 * v, m),
    )

    return {
        **collected,
        "insights": mined["insights"],
        "mine_results": mined["results"],
        "message": (
            f"{collected['posts']} bài, {collected['comments']} bình luận, "
            f"{mined['insights']} insight."
        ),
    }


def run_paste(req: PasteRequest) -> dict:
    """Dán tay chạy đồng bộ luôn — dữ liệu nhỏ, không cần job nền."""
    collected = ingest.collect_from_paste(
        req.source_id, req.post_text, req.comments_text, req.url, req.reactions, req.shares
    )
    post_id = collected["post_ids"][0]
    mined = mine.mine_post(post_id, MineSettings())
    return {**collected, **mined}


def run_mine(job: Job, post_ids: list[str], settings: MineSettings) -> dict:
    return mine.mine_posts(
        post_ids, settings,
        lambda v, m: manager.progress(job.id, "Đào insight", v, m),
    )


# ---------------------------------------------------------------------------
# Bước 2b — viết bài
# ---------------------------------------------------------------------------


def run_write(job: Job, insight_ids: list[str], settings: WriteSettings) -> dict:
    result = create.drafts_for_insights(
        insight_ids, settings,
        lambda v, m: manager.progress(job.id, "Viết bài", v, m),
    )
    flagged = sum(1 for d in result["drafts"] if d.get("warnings"))
    return {
        "count": result["count"],
        "flagged": flagged,
        "errors": result["errors"],
        "draft_ids": [d["id"] for d in result["drafts"]],
        "message": (
            f"Viết xong {result['count']} bài"
            + (f", {flagged} bài bị gắn cờ cần sửa tay trước khi duyệt." if flagged else ".")
        ),
    }


def recheck_draft(draft_id: str, settings: WriteSettings | None = None) -> dict | None:
    """Người duyệt sửa tay xong thì đo lại độ trùng lặp — cảnh báo tự mất khi đã sửa đủ."""
    draft = store.get_draft(draft_id)
    if not draft:
        return None
    post = store.get_post(draft.get("post_id") or "") or {}
    verdict = originality.check(
        originality.full_text(draft), post.get("text") or "", settings or WriteSettings()
    )
    return store.update_draft(
        draft_id, similarity=verdict["similarity"], warnings=verdict["warnings"]
    )
