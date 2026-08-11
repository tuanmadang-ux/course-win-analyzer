"""Chuẩn hoá dữ liệu thô về một dạng duy nhất — và ẩn danh người bình luận.

Nguyên tắc: hệ thống này quan tâm NGƯỜI TA HỎI GÌ, không quan tâm AI hỏi.
Nên ngay ở cửa vào, tên người bình luận bị băm thành mã ẩn danh, còn số điện
thoại / email / thẻ @tên trong nội dung bị xoá. Insight vẫn nguyên vẹn, mà
kho dữ liệu thì không chứa thông tin cá nhân của người lạ.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any

from radar.config import RADAR_DIR

_SALT_PATH = RADAR_DIR / "author_salt"


def _salt() -> bytes:
    """Muối ngẫu nhiên của từng máy: cùng một người thì cùng mã, nhưng không
    thể tra ngược ra tên, và hai máy khác nhau cho ra mã khác nhau."""
    if not _SALT_PATH.exists():
        _SALT_PATH.write_bytes(os.urandom(32))
    return _SALT_PATH.read_bytes()


def anonymize(author: str | None) -> str:
    if not author:
        return ""
    digest = hashlib.sha256(_salt() + author.strip().lower().encode("utf-8")).hexdigest()
    return "nd_" + digest[:10]


_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)\d{8,10}(?!\d)")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
_MENTION = re.compile(r"@[\wÀ-ỹ]+(?:\s+[\wÀ-ỹ]+){0,2}")
_URL = re.compile(r"https?://\S+")
_SPACES = re.compile(r"[ \t]+")


def scrub(text: str | None) -> str:
    """Xoá thông tin liên lạc và thẻ tên khỏi nội dung bình luận."""
    if not text:
        return ""
    t = _EMAIL.sub("[email]", text)
    t = _PHONE.sub("[sđt]", t)
    t = _MENTION.sub("[tên]", t)
    t = _URL.sub("[link]", t)
    t = _SPACES.sub(" ", t)
    return t.strip()


def clean_text(text: str | None) -> str:
    """Dọn nội dung bài viết (giữ nguyên chữ, chỉ bỏ khoảng trắng thừa)."""
    if not text:
        return ""
    lines = [_SPACES.sub(" ", ln).strip() for ln in text.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln and out and not out[-1]:
            continue
        out.append(ln)
    return "\n".join(out).strip()


def pick(d: dict, *keys: str, default: Any = None) -> Any:
    """Lấy giá trị đầu tiên tìm thấy — mỗi nhà cung cấp đặt tên trường một kiểu."""
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
        # hỗ trợ đường dẫn lồng nhau kiểu "stats.likes"
        if "." in k:
            cur: Any = d
            for part in k.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    cur = None
                    break
            if cur not in (None, ""):
                return cur
    return default


def to_int(value: Any) -> int:
    """Số tương tác hay về dạng '1,2K' hoặc '3.4N' — quy về số nguyên."""
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return 0
    s = value.strip().lower().replace(".", "").replace(",", ".").replace(" ", "")
    mult = 1
    for suffix, m in (("k", 1_000), ("n", 1_000), ("m", 1_000_000), ("tr", 1_000_000)):
        if s.endswith(suffix):
            s, mult = s[: -len(suffix)], m
            break
    try:
        return int(float(s) * mult)
    except ValueError:
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits else 0


def to_epoch(value: Any) -> float | None:
    """Nhận epoch, ISO-8601, hoặc 'dd/mm/yyyy'. Không đoán được thì trả None."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v          # mili giây -> giây
    s = str(value).strip()
    if s.isdigit():
        v = float(s)
        return v / 1000.0 if v > 1e11 else v
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def normalize_post(raw: dict, source_id: str, adapter: str) -> dict:
    return {
        "source_id": source_id,
        "adapter": adapter,
        "external_id": str(pick(raw, "postId", "post_id", "id", "pageAdLibrary.id", default="") or ""),
        "url": str(pick(raw, "url", "postUrl", "link", "permalink", "permalink_url", default="") or ""),
        "text": clean_text(pick(raw, "text", "message", "content", "caption", "post_text", default="")),
        "posted_at": to_epoch(pick(raw, "time", "timestamp", "created_time", "date", "publishedAt")),
        "reactions": to_int(pick(raw, "likes", "reactionsCount", "likesCount", "reactions", default=0)),
        "comment_count": to_int(pick(raw, "comments", "commentsCount", "comment_count", default=0)),
        "shares": to_int(pick(raw, "shares", "sharesCount", "share_count", default=0)),
    }


def normalize_comment(raw: dict) -> dict:
    author = pick(raw, "profileName", "authorName", "author", "name", "from.name", "user.name")
    return {
        "external_id": str(pick(raw, "commentId", "comment_id", "id", default="") or ""),
        "text": scrub(pick(raw, "text", "message", "comment", "content", default="")),
        "likes": to_int(pick(raw, "likesCount", "likes", "reactionsCount", default=0)),
        "replies": to_int(pick(raw, "repliesCount", "replies", "comment_count", default=0)),
        "author_hash": anonymize(author if isinstance(author, str) else None),
        "created_at": to_epoch(pick(raw, "date", "timestamp", "created_time", "time")),
    }
