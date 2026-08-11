"""Bước 2b — Sinh bài nháp từ insight đã chọn."""

from __future__ import annotations

from typing import Callable

from radar import store
from radar.config import WriteSettings
from radar.create import write as writer

Progress = Callable[[float, str], None]


def _noop(_value: float, _message: str) -> None:
    return None


def drafts_for_insights(insight_ids: list[str], settings: WriteSettings,
                        on_progress: Progress = _noop) -> dict:
    made: list[dict] = []
    errors: list[str] = []
    formats = settings.formats or ("post",)
    total = max(1, len(insight_ids) * len(formats) * settings.drafts_per_insight)
    done = 0

    for insight_id in insight_ids:
        insight = store.get_insight(insight_id)
        if not insight:
            errors.append(f"Không tìm thấy insight {insight_id}")
            continue
        post = store.get_post(insight["post_id"]) or {}

        for fmt in formats:
            for _ in range(max(1, settings.drafts_per_insight)):
                done += 1
                on_progress(done / total, f"Đang viết bài {done}/{total} ({fmt})…")
                draft = writer.write_draft(insight, post, fmt, settings)
                made.append(store.add_draft(draft))

        store.set_insight_status(insight_id, "used")

    return {"drafts": made, "count": len(made), "errors": errors}
