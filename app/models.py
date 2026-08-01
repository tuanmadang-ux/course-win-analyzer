"""Khai báo dữ liệu vào/ra cho API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    upload_id: str
    language: str = "vi"
    cut: dict[str, Any] | None = None
    broll: dict[str, Any] | None = None


class RenderRequest(BaseModel):
    project_id: str
    cuts: list[dict[str, Any]] = Field(default_factory=list)
    brolls: list[dict[str, Any]] = Field(default_factory=list)
    cut: dict[str, Any] | None = None
    render: dict[str, Any] | None = None


class BrollSearchRequest(BaseModel):
    query: str
    line: str = ""
