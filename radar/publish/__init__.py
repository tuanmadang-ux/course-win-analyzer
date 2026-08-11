"""Bước 3 — Duyệt tay rồi mới đăng.

Chốt chặn cố ý đặt cứng trong code, không cho tắt bằng cấu hình:

  * Bài phải được người duyệt bấm "Duyệt" thì mới lên lịch / đăng được.
  * Bài còn cảnh báo trùng lặp thì bị chặn cho tới khi sửa xong.
  * Bài rỗng thì không đăng.

Tự động hoá là để bạn đỡ mất thì giờ đọc 200 bình luận, không phải để bạn khỏi
phải đọc bài của chính mình trước khi nó lên trang.
"""

from __future__ import annotations

import time

from radar import store
from radar.create.originality import full_text
from radar.publish import facebook, schedule


class PublishBlocked(RuntimeError):
    """Bài chưa đủ điều kiện để lên lịch/đăng."""


def _gate(draft: dict) -> str:
    """Kiểm tra điều kiện đăng. Trả về nội dung bài nếu qua, ném lỗi nếu không."""
    if draft.get("warnings"):
        raise PublishBlocked("Bài còn cảnh báo chưa xử lý: " + " ".join(draft["warnings"]))
    if draft.get("status") not in ("approved", "scheduled"):
        raise PublishBlocked("Bài chưa được duyệt. Đọc lại rồi bấm Duyệt trước đã.")

    text = full_text(draft)
    if len(text.strip()) < 30:
        raise PublishBlocked("Nội dung bài quá ngắn hoặc đang trống.")
    return text


def approve(draft_id: str) -> dict:
    draft = store.get_draft(draft_id)
    if not draft:
        raise PublishBlocked("Không tìm thấy bài.")
    if draft.get("warnings"):
        raise PublishBlocked(
            "Không duyệt được khi bài còn cảnh báo. Sửa nội dung là hệ thống đo lại ngay. "
            + " ".join(draft["warnings"])
        )
    return store.update_draft(draft_id, status="approved")  # type: ignore[return-value]


def reject(draft_id: str) -> dict:
    return store.update_draft(draft_id, status="rejected")  # type: ignore[return-value]


def _taken_slots() -> list[float]:
    return [
        d["scheduled_at"] for d in store.list_drafts()
        if d.get("scheduled_at") and d.get("status") in ("scheduled", "published")
    ]


def plan(draft_id: str, scheduled_at: float | None = None) -> dict:
    """Lên lịch đăng. Có token trang thì đẩy luôn lịch lên Facebook;
    chưa có thì giữ lịch nội bộ để tới giờ nhắc bạn đăng tay."""
    draft = store.get_draft(draft_id)
    if not draft:
        raise PublishBlocked("Không tìm thấy bài.")
    message = _gate(draft)

    when = scheduled_at or schedule.next_slot(_taken_slots())
    now = time.time()
    if when < now + facebook.MIN_LEAD_SECONDS:
        when = now + facebook.MIN_LEAD_SECONDS
    if when > now + facebook.MAX_LEAD_SECONDS:
        raise PublishBlocked("Facebook chỉ cho hẹn giờ trong vòng 6 tháng.")

    published_id = ""
    if facebook.has_page():
        published_id = facebook.publish(message, scheduled_at=when).get("id", "")

    updated = store.update_draft(
        draft_id, status="scheduled", scheduled_at=when, published_id=published_id
    )
    return {
        **(updated or {}),
        "slot_label": schedule.describe(when),
        "on_facebook": bool(published_id),
    }


def publish_now(draft_id: str) -> dict:
    draft = store.get_draft(draft_id)
    if not draft:
        raise PublishBlocked("Không tìm thấy bài.")
    message = _gate(draft)

    if not facebook.has_page():
        raise PublishBlocked(
            "Chưa có FB_PAGE_ID / FB_PAGE_TOKEN. Bạn vẫn có thể copy nội dung và đăng tay."
        )

    result = facebook.publish(message)
    return store.update_draft(  # type: ignore[return-value]
        draft_id, status="published", published_id=result.get("id", ""), published_at=time.time()
    )


def due_now() -> list[dict]:
    """Bài tới giờ mà hệ thống không tự đăng được (chưa nối Graph API)."""
    return [d for d in store.due_drafts(time.time()) if not d.get("published_id")]
