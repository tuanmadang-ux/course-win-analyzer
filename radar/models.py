"""Khai báo dữ liệu vào/ra của các route API."""

from __future__ import annotations

from pydantic import BaseModel


class SourceRequest(BaseModel):
    name: str
    ref: str = ""              # link fanpage / username đối thủ
    platform: str = "facebook"
    note: str = ""


class PasteRequest(BaseModel):
    """Dán tay: nội dung bài + phần bình luận copy từ màn hình."""

    source_id: str
    post_text: str
    comments_text: str = ""
    url: str = ""
    reactions: int = 0
    shares: int = 0


class CollectRequest(BaseModel):
    """Thu thập tự động qua nhà cung cấp bạn đã đăng ký (Apify)."""

    source_id: str
    adapter: str = "apify"     # apify | file
    target: str = ""           # link fanpage, hoặc tên file đã tải lên
    mine: dict | None = None
    with_comments: bool = True


class MineRequest(BaseModel):
    post_ids: list[str] = []
    mine: dict | None = None


class WriteRequest(BaseModel):
    insight_ids: list[str]
    write: dict | None = None


class DraftUpdate(BaseModel):
    hook: str | None = None
    body: str | None = None
    cta: str | None = None
    angle: str | None = None
    status: str | None = None


class ScheduleRequest(BaseModel):
    draft_id: str
    scheduled_at: float | None = None   # epoch seconds; bỏ trống = dùng khung giờ vàng
    publish_now: bool = False
