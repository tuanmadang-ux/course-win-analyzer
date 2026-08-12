"""Biến nội dung gõ vào thành danh sách câu thoại có gán người nói.

Có Gemini thì nhờ nó biên tập lại cho dễ nói và chia câu hợp nhịp video ngắn.
Không có key — hoặc người dùng tắt biên tập — thì tự chẻ câu bằng dấu chấm,
để phần mềm vẫn dùng được. Cả hai đường đều trả về cùng một cấu trúc.
"""

from __future__ import annotations

import logging
import re

from app.avatar import gemini
from app.config import AvatarSettings

log = logging.getLogger(__name__)

# Người dùng có thể tự đánh dấu người nói: "A:", "B:", "1:", "Nam:", "Minh:" …
SPEAKER_TAG = re.compile(r"^\s*([AB1-2]|[\wÀ-ỹ]{1,12})\s*[:：]\s*", re.I)

STYLE_HINTS = {
    "than_thien": "thân thiện, gần gũi, như đang nói chuyện với bạn bè",
    "chuyen_nghiep": "chuyên nghiệp, rành mạch, đáng tin cậy",
    "nang_dong": "năng động, nhiệt, nhịp nhanh, hợp TikTok",
    "tam_su": "chậm rãi, tâm sự, có cảm xúc",
}

# Nói tiếng Việt tốc độ vừa phải rơi vào khoảng 4.5 âm tiết/giây.
SYLLABLES_PER_SECOND = 4.5


def style_hint(settings: AvatarSettings) -> str:
    """Câu chỉ dẫn diễn cảm đưa vào prompt TTS."""
    tone = STYLE_HINTS.get(settings.style, STYLE_HINTS["than_thien"])
    return f"Đọc bằng giọng {tone}, tốc độ {settings.speaking_rate}"


def estimate_seconds(text: str) -> float:
    """Ước lượng thời lượng đọc — dùng để canh độ dài kịch bản trước khi gọi TTS."""
    syllables = len([w for w in re.split(r"\s+", text.strip()) if w])
    return syllables / SYLLABLES_PER_SECOND


SYSTEM = """Bạn là biên kịch video ngắn dọc (TikTok / Reels / Shorts) người Việt.
Nhiệm vụ: biến nội dung thô của người dùng thành lời thoại ĐỌC LÊN nghe tự nhiên.

Nguyên tắc:
- Viết như nói, không viết như văn bản. Câu ngắn, chủ ngữ rõ, bỏ từ Hán Việt nặng nề.
- Câu đầu tiên phải là câu móc (hook) giữ người xem trong 2 giây đầu.
- Mỗi câu thoại dài 4–14 từ. Câu dài hơn thì tách ra.
- Không thêm emoji, không thêm ký hiệu, không ghi chú sân khấu. Chỉ lời nói.
- Giữ nguyên số liệu, tên riêng, tên thương hiệu người dùng đưa vào. Không bịa thêm.
- Kết thúc bằng một lời kêu gọi hành động ngắn nếu nội dung gốc có ý đó."""


def _prompt(content: str, settings: AvatarSettings, speakers: int) -> str:
    tone = STYLE_HINTS.get(settings.style, STYLE_HINTS["than_thien"])
    who = (
        "Chỉ có MỘT người nói, luôn đặt speaker = 1."
        if speakers < 2
        else (
            "Có HAI người nói, đặt speaker = 1 hoặc 2. Cho họ đối đáp qua lại tự nhiên, "
            "đừng để một người độc thoại quá 3 câu liên tiếp."
        )
    )
    return f"""Nội dung thô của người dùng:
---
{content.strip()}
---

Giọng điệu cần có: {tone}.
{who}
Tổng thời lượng đọc mục tiêu: khoảng {int(settings.max_seconds)} giây
(tương đương khoảng {int(settings.max_seconds * SYLLABLES_PER_SECOND)} từ).

Trả về JSON đúng dạng:
{{
  "title": "tiêu đề ngắn cho video",
  "music_mood": "mô tả 3-6 từ về nhạc nền hợp với video này",
  "segments": [
    {{"speaker": 1, "text": "câu thoại", "emotion": "một từ: vui/nghiêm túc/hào hứng/nhẹ nhàng"}}
  ]
}}"""


def plan(content: str, settings: AvatarSettings, speakers: int) -> dict:
    """Trả về {"title", "music_mood", "segments":[{speaker, text, emotion}]}."""
    content = (content or "").strip()
    if not content:
        raise ValueError("Chưa nhập nội dung cho video.")

    if settings.rewrite_script and gemini.available():
        try:
            data = gemini.generate_json(_prompt(content, settings, speakers), system=SYSTEM)
            plan_out = _clean(data, speakers)
            if plan_out["segments"]:
                return plan_out
            log.warning("Gemini trả kịch bản rỗng — dùng cách chẻ câu thủ công.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Không biên tập được bằng Gemini (%s) — dùng nội dung gốc.", exc)

    return _split_manually(content, speakers)


def _clean(data: object, speakers: int) -> dict:
    """Gemini đôi khi trả list thẳng hoặc thiếu trường — nắn về đúng dạng."""
    if isinstance(data, list):
        data = {"segments": data}
    if not isinstance(data, dict):
        raise ValueError("Kịch bản trả về không đúng dạng.")

    segments: list[dict] = []
    for raw in data.get("segments") or []:
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict):
            continue
        text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
        if not text:
            continue
        try:
            speaker = int(raw.get("speaker") or 1)
        except (TypeError, ValueError):
            speaker = 1
        segments.append({
            "index": len(segments),
            "speaker": 1 if speakers < 2 else min(max(speaker, 1), 2),
            "text": text,
            "emotion": str(raw.get("emotion") or "").strip(),
        })

    return {
        "title": str(data.get("title") or "").strip(),
        "music_mood": str(data.get("music_mood") or "").strip(),
        "segments": segments,
    }


def _split_manually(content: str, speakers: int) -> dict:
    """Chẻ câu không cần AI: tôn trọng nhãn người nói và dấu xuống dòng."""
    segments: list[dict] = []
    current = 1

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        tag = SPEAKER_TAG.match(line)
        if tag and speakers >= 2:
            token = tag.group(1).upper()
            # Nhãn quen thuộc thì map thẳng, tên riêng thì luân phiên hai người
            current = 2 if token in ("B", "2") else 1 if token in ("A", "1") else current
            line = line[tag.end():].strip()
            if not line:
                continue

        for sentence in re.split(r"(?<=[.!?…])\s+", line):
            sentence = re.sub(r"\s+", " ", sentence).strip()
            if not sentence:
                continue
            segments.append({
                "index": len(segments),
                "speaker": current,
                "text": sentence,
                "emotion": "",
            })

        # Không có nhãn mà người dùng muốn 2 người -> đổi vai theo từng dòng
        if speakers >= 2 and not tag:
            current = 2 if current == 1 else 1

    return {"title": "", "music_mood": "", "segments": segments}
