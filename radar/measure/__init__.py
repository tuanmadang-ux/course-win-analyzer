"""Bước 4 — Đo lường và tìm ra công thức nào đang ăn.

Câu hỏi cần trả lời không phải "bài này được bao nhiêu like", mà là: dạng
insight nào (câu hỏi? phản đối?) và định dạng nào (bài dài? reels?) đang cho
tương tác tốt nhất — để lần sau nhân bản đúng công thức đó.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from radar import store
from radar.config import FORMAT_LABELS
from radar.mine.insight import KIND_LABELS
from radar.publish import facebook

log = logging.getLogger(__name__)

# Bài mới đăng chưa có số liệu ổn định; dưới ngưỡng này chỉ ghi nhận, không xếp hạng
MIN_AGE_HOURS = 6


def refresh() -> dict:
    """Kéo chỉ số mới nhất cho mọi bài đã đăng qua hệ thống."""
    if not facebook.has_page():
        return {"updated": 0, "error": "Chưa nối Fanpage — không đọc được chỉ số."}

    now = time.time()
    updated, errors = 0, []

    for draft in store.list_drafts():
        post_id = draft.get("published_id")
        if not post_id or draft.get("status") not in ("scheduled", "published"):
            continue

        # Bài hẹn giờ: qua giờ đăng rồi thì coi như đã lên trang
        if draft["status"] == "scheduled" and (draft.get("scheduled_at") or 0) <= now:
            store.update_draft(draft["id"], status="published",
                               published_at=draft.get("scheduled_at") or now)
        elif draft["status"] == "scheduled":
            continue

        try:
            metrics = facebook.post_metrics(post_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{draft['id']}: {exc}")
            continue
        store.record_metrics(draft["id"], metrics)
        updated += 1

    return {"updated": updated, "errors": errors[:10]}


def _rows() -> list[dict]:
    """Ghép bài đã đăng với chỉ số mới nhất của nó."""
    metrics = store.latest_metrics()
    now = time.time()
    out = []
    for draft in store.list_drafts():
        m = metrics.get(draft["id"])
        if not m:
            continue
        published_at = draft.get("published_at") or draft.get("scheduled_at") or 0
        out.append({
            "draft_id": draft["id"],
            "hook": draft.get("hook", ""),
            "format": draft.get("format", "post"),
            "insight_kind": draft.get("insight_kind") or "",
            "insight_title": draft.get("insight_title") or "",
            "published_at": published_at,
            "mature": bool(published_at) and (now - published_at) >= MIN_AGE_HOURS * 3600,
            "reach": m["reach"],
            "impressions": m["impressions"],
            "reactions": m["reactions"],
            "comments": m["comments"],
            "shares": m["shares"],
            "clicks": m["clicks"],
            "engagement_rate": m["engagement_rate"],
            "engaged": m["reactions"] + m["comments"] + m["shares"] + m["clicks"],
        })
    out.sort(key=lambda r: r["published_at"], reverse=True)
    return out


def _group(rows: list[dict], key: str, labels: dict[str, str]) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[r.get(key) or "(không rõ)"].append(r)

    out = []
    for name, items in buckets.items():
        n = len(items)
        out.append({
            "key": name,
            "label": labels.get(name, name),
            "posts": n,
            "avg_engagement_rate": round(sum(i["engagement_rate"] for i in items) / n, 4),
            "avg_reach": round(sum(i["reach"] for i in items) / n),
            "avg_engaged": round(sum(i["engaged"] for i in items) / n, 1),
            "best_hook": max(items, key=lambda i: i["engaged"])["hook"][:120],
        })
    out.sort(key=lambda g: (g["avg_engagement_rate"], g["avg_engaged"]), reverse=True)
    return out


def report() -> dict:
    """Bảng tổng hợp cho tab Hiệu suất."""
    rows = _rows()
    mature = [r for r in rows if r["mature"]] or rows

    verdict = ""
    if len(mature) >= 3:
        by_kind = _group(mature, "insight_kind", KIND_LABELS)
        by_format = _group(mature, "format", FORMAT_LABELS)
        if by_kind and by_format:
            verdict = (
                f"Công thức đang ăn nhất: insight dạng “{by_kind[0]['label']}” "
                f"viết theo định dạng “{by_format[0]['label']}” "
                f"({by_kind[0]['avg_engagement_rate'] * 100:.1f}% tương tác trung bình). "
                f"Nhân bản công thức này trước khi thử cái khác."
            )
    elif rows:
        verdict = f"Mới có {len(rows)} bài có số liệu — cần ít nhất 3 bài để kết luận."

    return {
        "posts": len(rows),
        "verdict": verdict,
        "by_kind": _group(mature, "insight_kind", KIND_LABELS) if mature else [],
        "by_format": _group(mature, "format", FORMAT_LABELS) if mature else [],
        "top": sorted(rows, key=lambda r: r["engagement_rate"], reverse=True)[:10],
        "recent": rows[:20],
    }
