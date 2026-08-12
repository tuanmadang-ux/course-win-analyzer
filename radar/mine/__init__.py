"""Bước 2a — Đào insight từ phần bình luận.

    chấm điểm (quality) → lọc → gom cụm (cluster) → tổng hợp (insight)
"""

from __future__ import annotations

from typing import Callable

from radar import store
from radar.config import MineSettings
from radar.mine import cluster as cluster_mod
from radar.mine import insight as insight_mod
from radar.mine import quality

Progress = Callable[[float, str], None]


def _noop(_value: float, _message: str) -> None:
    return None


def mine_post(post_id: str, settings: MineSettings) -> dict:
    """Đào một bài: chấm điểm bình luận, gom cụm, sinh insight."""
    post = store.get_post(post_id)
    if not post:
        return {"post_id": post_id, "insights": [], "error": "Không tìm thấy bài."}

    comments = store.comments_for_post(post_id)
    if not comments:
        return {"post_id": post_id, "insights": [], "error": "Bài này chưa có bình luận nào."}

    scored = quality.score_all(comments, settings)
    store.update_comment_scores(scored)

    kept = quality.keepers(scored, settings)
    if not kept:
        return {
            "post_id": post_id, "insights": [],
            "error": f"{len(comments)} bình luận nhưng không cái nào đủ chất "
                     f"(toàn khen xã giao / quá ngắn).",
        }

    clusters = cluster_mod.cluster_comments(kept, settings)
    insights = insight_mod.extract(post, clusters)
    saved = store.replace_insights(post_id, insights)
    store.set_post_status(post_id, "mined")

    return {
        "post_id": post_id,
        "post_text": (post.get("text") or "")[:200],
        "comments": len(comments),
        "kept": len(kept),
        "clusters": len(clusters),
        "insights": saved,
    }


def mine_posts(post_ids: list[str], settings: MineSettings,
               on_progress: Progress = _noop) -> dict:
    results = []
    total_insights = 0
    for i, pid in enumerate(post_ids):
        on_progress((i + 0.5) / max(1, len(post_ids)), f"Đang đào bài {i + 1}/{len(post_ids)}…")
        r = mine_post(pid, settings)
        total_insights += len(r.get("insights", []))
        results.append(r)
    return {"posts": len(post_ids), "insights": total_insights, "results": results}
