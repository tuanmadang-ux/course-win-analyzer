"""Cách vào dữ liệu đơn giản nhất: dán tay.

Bạn mở bài của đối thủ, bấm "Xem thêm bình luận" cho hết, quét chọn rồi copy
dán vào ô. Hàm dưới đây tách khối chữ lộn xộn đó thành từng bình luận riêng,
bỏ các dòng rác kiểu "Thích · Trả lời · 2 ngày".

Không cần key, không đụng gì tới Facebook — nhưng vẫn đủ dữ liệu để đào insight.
"""

from __future__ import annotations

import re

# "Thích · Trả lời · 2 ngày", "Like · Reply · 3h", "12 phút trước"
_META = re.compile(
    r"^(?:\d+\s*)?(?:thích|like|trả lời|reply|phản hồi|đã chỉnh sửa|edited"
    r"|xem thêm \d+ (?:phản hồi|câu trả lời)|\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|[smhdw])\b.*)"
    r"(?:\s*[·•|-]\s*.*)?$",
    re.IGNORECASE,
)
# Dòng chỉ có số + biểu tượng cảm xúc (bộ đếm reaction)
_COUNT_ONLY = re.compile(r"^[\d\s.,KkMmNn👍❤️😆😮😢😡🥰:·•|-]+$")
_LIKES_IN_META = re.compile(r"(\d[\d.,]*)\s*(?:lượt thích|likes?)", re.IGNORECASE)
_NAME_LINE = re.compile(r"^[^\n]{2,48}$")
_SENTENCE_END = re.compile(r"[.!?…,:;]$")


def _looks_like_name(line: str) -> bool:
    """Dòng tên người: ngắn, ít từ, không kết câu, không phải câu hỏi."""
    if not _NAME_LINE.match(line) or "?" in line:
        return False
    words = line.split()
    if not (1 <= len(words) <= 6):
        return False
    if _SENTENCE_END.search(line):
        return False
    # Tên người Việt viết hoa chữ đầu mỗi từ; câu bình luận thường không thế.
    capitalised = sum(1 for w in words if w[:1].isupper())
    return capitalised >= max(1, len(words) - 1)


def _clean_block(block: str) -> tuple[str, str, int]:
    """Trả về (tên, nội dung, số lượt thích) từ một khối chữ."""
    lines = [ln.strip() for ln in block.split("\n")]
    lines = [ln for ln in lines if ln]

    likes = 0
    body: list[str] = []
    author = ""

    for i, line in enumerate(lines):
        if _META.match(line) or _COUNT_ONLY.match(line):
            m = _LIKES_IN_META.search(line)
            if m:
                likes = max(likes, int(re.sub(r"[^\d]", "", m.group(1)) or 0))
            else:
                digits = re.sub(r"[^\d]", "", line)
                if digits and _COUNT_ONLY.match(line):
                    likes = max(likes, int(digits))
            continue
        if i == 0:
            # "Tên: nội dung" trên cùng một dòng
            if ":" in line:
                head, _, tail = line.partition(":")
                if _looks_like_name(head.strip()) and len(tail.strip()) > 2:
                    author = head.strip()
                    body.append(tail.strip())
                    continue
            if _looks_like_name(line) and len(lines) > 1:
                author = line
                continue
        body.append(line)

    return author, " ".join(body).strip(), likes


def parse_comments(text: str) -> list[dict]:
    """Tách khối chữ dán vào thành danh sách bình luận thô."""
    if not text or not text.strip():
        return []

    raw = text.replace("\r\n", "\n").strip()
    blocks = [b for b in re.split(r"\n\s*\n", raw) if b.strip()]

    # Dán kiểu mỗi bình luận một dòng (không có dòng trống ngăn cách)
    if len(blocks) == 1 and raw.count("\n") >= 2:
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        meta_ratio = sum(1 for ln in lines if _META.match(ln)) / len(lines)
        if meta_ratio < 0.15:
            blocks = lines

    out: list[dict] = []
    for i, block in enumerate(blocks):
        author, body, likes = _clean_block(block)
        body = re.sub(r"^[-•*–]\s*", "", body).strip()
        if len(body) < 2:
            continue
        out.append({
            "id": f"paste_{i}",
            "profileName": author,
            "text": body,
            "likesCount": likes,
        })
    return out
