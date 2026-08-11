"""Chấm điểm bình luận: cái nào là "mỏ vàng", cái nào là "hay quá ạ".

Chạy hoàn toàn offline. Mục tiêu không phải chấm đúng tuyệt đối, mà là dồn
đúng nhóm bình luận đáng đọc lên đầu trước khi tốn lượt gọi AI cho chúng.
"""

from __future__ import annotations

import math
import re

from radar.config import MineSettings
from radar.mine.text import strip_accents, words

# --- Dấu hiệu nhận dạng ------------------------------------------------------
#
# Viết không dấu để bắt được cả người gõ thiếu dấu. Và BẮT BUỘC khớp theo ranh
# giới từ: để khớp chuỗi con thì "do" (dở) khớp luôn vào "đóng", "cham" (chậm)
# khớp vào "chăm" — bình luận khen cũng bị đọc thành chê.


def _rx(cues: tuple[str, ...]) -> re.Pattern[str]:
    body = "|".join(re.escape(c) for c in cues)
    return re.compile(rf"(?<![\w]){body}(?![\w])")


_QUESTION_CUES = (
    "cho hoi", "cho minh hoi", "cho em hoi", "hoi chut", "tu van", "co ai biet",
    "the nao", "nhu nao", "nhu the nao", "lam sao", "lam the nao", "bao nhieu",
    "bao lau", "khi nao", "o dau", "co can", "co nen", "co hieu qua", "co that",
    "khac gi", "so voi", "tai sao", "vi sao", "sao lai", "duoc khong", "dc ko",
    "gia bao nhieu", "bao gio", "may gio", "may nguoi", "may buoi", "ra sao",
    "gi vay", "gi the", "gi a", "gi khong", "nao vay", "nao the", "dau a",
    "cam ket khong", "co cam ket", "hay khong", "phai khong", "dung khong",
    # câu hỏi lựa chọn "… hay …", thường không có dấu chấm hỏi
    "hay phai", "hay la", "hay van", "hay chi",
)
# Người Việt hỏi mà không cần dấu chấm hỏi: "có ... không ạ", "học được không"
_QUESTION_PATTERNS = (
    re.compile(r"(?<![\w])co(?![\w])[^.!?]{0,40}(?<![\w])(?:khong|ko|k)(?![\w])"),
    re.compile(r"(?<![\w])(?:khong|ko|chua|hem|ha)(?![\w])\s*(?:a|ad|ban|shop|e|em|chi|anh|vay|the)?\s*[?.!]*\s*$"),
)
_OBJECTION_CUES = (
    "nhung ma", "dat qua", "mac qua", "gia chat", "chat chem", "lua dao", "scam",
    "that vong", "khong hieu qua", "ko hieu qua", "phi tien", "mat tien",
    "chan qua", "chan that", "qua te", "te that", "kem qua", "do te", "cao qua",
    "ko dang", "khong dang", "khong xung", "quang cao lao", "noi vay thoi",
    "thuc te thi", "van de la", "kho lam", "khong lam duoc", "ko kha thi",
    "qua cham", "cham qua", "hoi nghi ngo", "khong tin", "chac gi", "tien mat",
    "khong dam", "ko dam", "so bi", "bi tu choi", "khong hoan", "ko hoan",
)
_EXPERIENCE_CUES = (
    "minh da", "em da", "toi da", "minh dung", "em dung", "da mua", "da hoc",
    "hoc roi", "hoc xong", "dung roi", "mua roi", "trai nghiem", "sau khi",
    "ket qua la", "minh tung", "em tung", "toi tung", "thuc te minh", "hoi truoc",
    "nam ngoai", "thang truoc", "minh hoc", "em hoc o", "minh mua",
)
_REQUEST_CUES = (
    "lam video", "ra bai", "chia se them", "co the noi ve", "muon biet them",
    "mong ad", "nho ad", "cho xin", "huong dan", "chi tiet hon", "vi du",
    "lam mot bai", "noi ky hon",
)
_NOISE_CUES = (
    "hay qua", "cam on", "tuyet voi", "qua dinh", "chuan", "like", "hong", "up",
    "hoc hoi", "theo doi", "diem danh", "co mat", "danh dau", "de danh", "luu lai",
    "quan tam", "dep qua", "ok", "oke",
)

_QUESTION_RX = _rx(_QUESTION_CUES)
_OBJECTION_RX = _rx(_OBJECTION_CUES)
_EXPERIENCE_RX = _rx(_EXPERIENCE_CUES)
_REQUEST_RX = _rx(_REQUEST_CUES)
_NOISE_RX = _rx(_NOISE_CUES)

_EMOJI_ONLY = re.compile(r"^[\W\d_]+$", re.UNICODE)
_TAG_ONLY = re.compile(r"^\s*(?:\[tên\]\s*)+$")

KIND_WEIGHT = {
    "question": 1.00,     # quý nhất: khách tự nói ra thứ họ chưa hiểu
    "objection": 0.95,    # phản đối / nghi ngờ — chỗ bài gốc chưa gỡ được
    "experience": 0.80,   # trải nghiệm thật — dùng làm dẫn chứng
    "request": 0.70,      # xin thêm nội dung — đề tài có sẵn
    "chitchat": 0.10,
}


def _is_question(text: str, flat: str) -> bool:
    if "?" in text or _QUESTION_RX.search(flat):
        return True
    return any(p.search(flat) for p in _QUESTION_PATTERNS)


def classify(text: str) -> str:
    flat = strip_accents((text or "").lower())

    objection = bool(_OBJECTION_RX.search(flat))
    if _is_question(text or "", flat):
        # Câu hỏi kèm giọng bức xúc thì tính là phản đối — đáng khai thác hơn
        return "objection" if objection else "question"
    if objection:
        return "objection"
    if _EXPERIENCE_RX.search(flat):
        return "experience"
    if _REQUEST_RX.search(flat):
        return "request"
    return "chitchat"


def score_comment(comment: dict, settings: MineSettings) -> dict:
    """Gắn `kind` và `score` (0..1) cho một bình luận."""
    text = comment.get("text", "") or ""
    tokens = words(text)
    flat = strip_accents(text.lower())

    if _EMOJI_ONLY.match(text) or _TAG_ONLY.match(text):
        return {**comment, "kind": "chitchat", "score": 0.0}

    kind = classify(text)
    base = KIND_WEIGHT.get(kind, 0.1)

    # Dài hơn thường là nghĩ nhiều hơn, nhưng bão hoà nhanh
    length_bonus = min(1.0, math.log1p(len(tokens)) / math.log1p(35))

    # Người khác thấy đúng ý mình thì họ thả tim / trả lời
    engage = math.log1p(comment.get("likes", 0) + 2 * comment.get("replies", 0))
    engage_bonus = min(1.0, engage / math.log1p(50))

    score = 0.55 * base + 0.25 * length_bonus + 0.20 * engage_bonus

    if len(tokens) < settings.min_comment_words:
        score *= 0.35
    if _NOISE_RX.search(flat) and len(tokens) < 8:
        score *= 0.3

    return {**comment, "kind": kind, "score": round(min(1.0, score), 4)}


def score_all(comments: list[dict], settings: MineSettings) -> list[dict]:
    return [score_comment(c, settings) for c in comments]


def keepers(scored: list[dict], settings: MineSettings) -> list[dict]:
    """Bình luận đủ điểm để đem đi gom cụm."""
    out = [
        c for c in scored
        if c["score"] >= settings.min_comment_score
        and len(words(c.get("text", ""))) >= settings.min_comment_words
        and c["kind"] != "chitchat"
    ]
    out.sort(key=lambda c: c["score"], reverse=True)
    return out
