"""Khai báo dữ liệu vào/ra cho API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    upload_id: str
    language: str = "vi"
    cut: dict[str, Any] | None = None
    broll: dict[str, Any] | None = None


class ReanalyzeRequest(BaseModel):
    cut: dict[str, Any] | None = None
    broll: dict[str, Any] | None = None
    redo_broll: bool = False


class RenderRequest(BaseModel):
    project_id: str
    cuts: list[dict[str, Any]] = Field(default_factory=list)
    brolls: list[dict[str, Any]] = Field(default_factory=list)
    cut: dict[str, Any] | None = None
    render: dict[str, Any] | None = None


class BrollSearchRequest(BaseModel):
    query: str
    line: str = ""


class AvatarGenerateRequest(BaseModel):
    """Tạo video người nói từ ảnh đã tải lên + nội dung gõ vào."""

    photo_ids: list[str] = Field(default_factory=list, max_length=2)
    content: str
    avatar: dict[str, Any] | None = None
    render: dict[str, Any] | None = None


class ScriptPreviewRequest(BaseModel):
    """Xem trước kịch bản đã biên tập mà chưa tốn lượt gọi TTS/lip-sync."""

    content: str
    speakers: int = 1
    avatar: dict[str, Any] | None = None
