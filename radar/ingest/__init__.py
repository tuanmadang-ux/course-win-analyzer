"""Bước 1 — Thu thập.

Bốn đường vào dữ liệu, cùng đổ về một chỗ (bảng posts + comments):

    dán tay   → paste.py      (không cần key, luôn dùng được)
    file      → filefeed.py   (CSV/JSON đã xuất từ công cụ khác)
    apify     → apify.py      (tự động, dùng token Apify của bạn)
    graph     → publish/facebook.py (chỉ cho trang CỦA BẠN)

Muốn thêm nguồn mới thì viết adapter trả về list[dict] thô rồi gọi
`save_post()` ở đây — normalize sẽ lo phần tên trường lệch nhau.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from radar import store
from radar.config import MineSettings
from radar.ingest import apify, filefeed, paste
from radar.ingest.normalize import normalize_comment, normalize_post

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]


def _noop(_value: float, _message: str) -> None:
    return None


def save_post(raw: dict, source_id: str, adapter: str, raw_comments: list[dict],
              settings: MineSettings) -> tuple[str, int]:
    """Ghi một bài + bình luận của nó. Trả về (post_id, số bình luận mới)."""
    post = normalize_post(raw, source_id, adapter)
    post_id = store.upsert_post(post)

    comments = []
    for rc in raw_comments[: settings.max_comments_per_post]:
        c = normalize_comment(rc)
        if c["text"]:
            comments.append(c)
    added = store.upsert_comments(post_id, comments) if comments else 0

    # Nguồn nào không trả sẵn số bình luận thì lấy số đếm thực tế
    if not post["comment_count"]:
        store.upsert_post({**post, "comment_count": store.comment_count(post_id)})
    return post_id, added


def keep_post(raw_post: dict, settings: MineSettings) -> tuple[bool, str]:
    """Bài có đáng đào không? Trả về (giữ, lý do bỏ)."""
    reactions = raw_post.get("reactions", 0)
    comments = raw_post.get("comment_count", 0)
    posted_at = raw_post.get("posted_at")

    if comments < settings.min_comments:
        return False, f"chỉ {comments} bình luận"
    if reactions < settings.min_reactions:
        return False, f"chỉ {reactions} tương tác"
    if posted_at and settings.max_age_days > 0:
        age_days = (time.time() - posted_at) / 86400
        if age_days > settings.max_age_days:
            return False, f"đã {age_days:.0f} ngày tuổi"
    if not (raw_post.get("text") or "").strip():
        return False, "bài không có chữ"
    return True, ""


# ---------------------------------------------------------------------------
# Dán tay
# ---------------------------------------------------------------------------


def collect_from_paste(source_id: str, post_text: str, comments_text: str, url: str = "",
                       reactions: int = 0, shares: int = 0) -> dict:
    raw_comments = paste.parse_comments(comments_text)
    raw_post = {
        "id": url or f"paste_{int(time.time())}",
        "url": url,
        "text": post_text,
        "likes": reactions,
        "shares": shares,
        "comments": len(raw_comments),
        "time": time.time(),
    }
    post_id, added = save_post(raw_post, source_id, "paste", raw_comments, MineSettings())
    return {"post_ids": [post_id], "posts": 1, "comments": added, "skipped": []}


# ---------------------------------------------------------------------------
# File đã xuất sẵn
# ---------------------------------------------------------------------------


def collect_from_file(source_id: str, path: Path, settings: MineSettings,
                      on_progress: Progress = _noop) -> dict:
    records = filefeed.load_records(path)
    if not records:
        raise ValueError("File không có bản ghi nào đọc được.")

    raw_posts, comment_map = filefeed.split_records(records)
    if not raw_posts:
        raise ValueError(
            "File chỉ có bình luận mà không có bài nào. Hãy xuất kèm bài gốc, "
            "hoặc dán bài bằng tay rồi nhập bình luận sau."
        )

    return _ingest_many(
        source_id, "file", raw_posts, settings, on_progress,
        get_comments=lambda rp: filefeed.comments_for(rp, comment_map),
    )


# ---------------------------------------------------------------------------
# Apify
# ---------------------------------------------------------------------------


def collect_from_apify(source_id: str, target: str, settings: MineSettings,
                       with_comments: bool = True, on_progress: Progress = _noop) -> dict:
    on_progress(0.05, "Đang gọi Apify lấy danh sách bài…")
    raw_posts = apify.fetch_posts(target, limit=settings.max_posts)
    if not raw_posts:
        raise ValueError("Apify không trả về bài nào. Kiểm tra link trang và cấu hình actor.")

    def _comments(raw_post: dict) -> list[dict]:
        if not with_comments:
            return []
        nested = raw_post.get("comments")
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            return nested
        url = normalize_post(raw_post, source_id, "apify")["url"]
        return apify.fetch_comments(url, limit=settings.max_comments_per_post)

    return _ingest_many(source_id, "apify", raw_posts, settings, on_progress,
                        get_comments=_comments)


# ---------------------------------------------------------------------------
# Vòng lặp chung
# ---------------------------------------------------------------------------


def _ingest_many(source_id: str, adapter: str, raw_posts: list[dict], settings: MineSettings,
                 on_progress: Progress,
                 get_comments: Callable[[dict], list[dict]]) -> dict:
    post_ids: list[str] = []
    skipped: list[str] = []
    total_comments = 0

    candidates = raw_posts[: settings.max_posts * 3]  # lọc xong mới đủ max_posts
    for i, raw_post in enumerate(candidates):
        if len(post_ids) >= settings.max_posts:
            break

        normalized = normalize_post(raw_post, source_id, adapter)
        ok, reason = keep_post(normalized, settings)
        if not ok:
            skipped.append(f"{(normalized['text'] or '(không chữ)')[:48]}… — bỏ vì {reason}")
            continue

        on_progress(
            0.1 + 0.8 * (i + 1) / len(candidates),
            f"Bài {len(post_ids) + 1}/{settings.max_posts}: đang lấy bình luận…",
        )
        try:
            raw_comments = get_comments(raw_post)
        except Exception as exc:  # noqa: BLE001 - hỏng 1 bài không được chết cả mẻ
            log.warning("Không lấy được bình luận: %s", exc)
            raw_comments = []

        post_id, added = save_post(raw_post, source_id, adapter, raw_comments, settings)
        post_ids.append(post_id)
        total_comments += added

    return {
        "post_ids": post_ids,
        "posts": len(post_ids),
        "comments": total_comments,
        "skipped": skipped[:20],
    }
