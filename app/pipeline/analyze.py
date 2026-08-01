"""Phân tích ngữ cảnh: vấp/nói lại, đoạn lạc đề, và lên kế hoạch B-roll.

Có hai chế độ:
  * Offline  — không cần API key, dùng thuật toán so trùng câu.
  * Claude   — khi có ANTHROPIC_API_KEY, hiểu được ý nghĩa nên chính xác hơn nhiều.
"""

from __future__ import annotations

import json
import logging
from difflib import SequenceMatcher

from app.config import ANALYSIS_MODEL, ANTHROPIC_API_KEY, BrollSettings, CutSettings, has_claude
from app.pipeline.fillers import normalize

log = logging.getLogger(__name__)

_MAX_SEGMENTS_PER_CALL = 120


# ---------------------------------------------------------------------------
# 1. Vấp / nói lại — chế độ offline
# ---------------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    return [t for t in (normalize(w) for w in (text or "").split()) if t]


def badtake_cuts_offline(segments: list[dict], settings: CutSettings) -> list[dict]:
    """Phát hiện câu bị nói lại: giữ lần cuối, cắt các lần trước."""
    if not settings.detect_badtakes:
        return []

    proposals: list[dict] = []
    for i, seg in enumerate(segments):
        a = _tokens(seg.get("text", ""))
        if len(a) < 3:
            continue
        for j in range(i + 1, len(segments)):
            nxt = segments[j]
            if nxt["start"] - seg["end"] > settings.badtake_window:
                break
            b = _tokens(nxt.get("text", ""))
            if len(b) < 3:
                continue
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= settings.badtake_similarity:
                proposals.append({
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "kind": "badtake",
                    "reason": f"Nói lại câu này ở giây {nxt['start']:.1f} (giống {ratio * 100:.0f}%)",
                    "text": seg.get("text", ""),
                    "enabled": True,
                })
                break
    return proposals


# ---------------------------------------------------------------------------
# 2. Gọi Claude
# ---------------------------------------------------------------------------


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _claude_json(system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict | None:
    """Gọi Claude và ép trả về JSON đúng schema. Lỗi thì trả None (không chặn pipeline)."""
    try:
        client = _client()
        resp = client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "refusal":
            log.warning("Claude từ chối phân tích đoạn này.")
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            return None
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001 - không được để pipeline chết vì API
        log.warning("Gọi Claude thất bại: %s", exc)
        return None


def _segments_as_text(segments: list[dict]) -> str:
    return "\n".join(
        f"[{s['id']}] {s['start']:.1f}-{s['end']:.1f}s: {s.get('text', '')}"
        for s in segments
    )


_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "bad_takes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["segment_id", "reason"],
                "additionalProperties": False,
            },
        },
        "off_topic": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["segment_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["topic", "bad_takes", "off_topic"],
    "additionalProperties": False,
}

_ANALYSIS_SYSTEM = """Bạn là một biên tập viên video chuyên nghiệp, người Việt.
Bạn nhận transcript của một video quay một mạch (chưa cắt), chia theo từng câu có đánh số.

Nhiệm vụ:
1. bad_takes — Tìm những câu người nói bị VẤP, NÓI LẮP, hoặc NÓI LẠI ý đó ở câu sau tốt hơn.
   Chỉ đánh dấu câu THỪA (lần nói hỏng). LUÔN giữ lại lần nói hoàn chỉnh/mượt nhất.
   Nếu không chắc chắn thì KHÔNG đánh dấu — thà giữ thừa còn hơn cắt nhầm ý hay.
2. off_topic — Tìm những câu lan man, lạc khỏi chủ đề chính, hoặc lặp ý đã nói rồi mà
   không thêm thông tin mới. Rất bảo thủ: chỉ chọn khi bỏ đi mà video vẫn liền mạch.
3. topic — Tóm tắt chủ đề chính của video trong 1 câu ngắn tiếng Việt.

Lý do (reason) viết bằng tiếng Việt, ngắn gọn, để người dùng đọc và quyết định."""


def claude_analyze(segments: list[dict], settings: CutSettings) -> dict:
    """Trả về {"topic": str, "badtakes": [...], "offtopic": [...]} (đã là proposal)."""
    if not has_claude() or not segments:
        return {"topic": "", "badtakes": [], "offtopic": []}

    by_id = {s["id"]: s for s in segments}
    topic = ""
    badtakes: list[dict] = []
    offtopic: list[dict] = []

    for start in range(0, len(segments), _MAX_SEGMENTS_PER_CALL):
        chunk = segments[start:start + _MAX_SEGMENTS_PER_CALL]
        user = (
            "Đây là transcript video cần biên tập:\n\n"
            + _segments_as_text(chunk)
            + "\n\nHãy phân tích theo đúng nhiệm vụ đã mô tả."
        )
        result = _claude_json(_ANALYSIS_SYSTEM, user, _ANALYSIS_SCHEMA)
        if not result:
            continue

        topic = topic or (result.get("topic") or "")

        if settings.detect_badtakes:
            for item in result.get("bad_takes", []):
                seg = by_id.get(item.get("segment_id"))
                if not seg:
                    continue
                badtakes.append({
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "kind": "badtake",
                    "reason": item.get("reason") or "Câu bị vấp / nói lại",
                    "text": seg.get("text", ""),
                    "enabled": True,
                })

        if settings.detect_offtopic:
            for item in result.get("off_topic", []):
                seg = by_id.get(item.get("segment_id"))
                if not seg:
                    continue
                offtopic.append({
                    "start": round(seg["start"], 3),
                    "end": round(seg["end"], 3),
                    "kind": "offtopic",
                    "reason": item.get("reason") or "Lạc đề / dài dòng",
                    "text": seg.get("text", ""),
                    # Cắt lạc đề mạnh tay nhất -> mặc định KHÔNG tick, để người dùng tự duyệt
                    "enabled": False,
                })

    return {"topic": topic, "badtakes": badtakes, "offtopic": offtopic}


# ---------------------------------------------------------------------------
# 3. Lên kế hoạch B-roll
# ---------------------------------------------------------------------------

_BROLL_SCHEMA = {
    "type": "object",
    "properties": {
        "slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "integer"},
                    "query_en": {"type": "string"},
                    "query_vi": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["segment_id", "query_en", "query_vi", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["slots"],
    "additionalProperties": False,
}

_BROLL_SYSTEM = """Bạn là biên tập viên video, chuyên chọn B-roll (hình cắt cảnh) cho video tiếng Việt.

Bạn nhận transcript chia theo câu có đánh số. Hãy chọn tối đa {max_slots} câu mà nếu chèn
B-roll lên trên (giữ nguyên tiếng nói) thì video sẽ hay hơn và MINH HOẠ ĐÚNG điều đang nói.

Quy tắc bắt buộc:
- B-roll phải minh hoạ ĐÚNG NỘI DUNG câu nói đó. Tuyệt đối không chọn hình chung chung
  kiểu "business people smiling" nếu câu đang nói về một thứ cụ thể.
- Ưu tiên câu mô tả sự vật, hành động, địa điểm, quá trình, con số — những thứ NHÌN ĐƯỢC.
- Bỏ qua câu chào hỏi, chuyển ý, kêu gọi like/share.
- Các câu được chọn nên rải đều video, không dồn cục.

Với mỗi câu được chọn, trả về:
- query_en: từ khoá TIẾNG ANH để tìm video stock (3-6 từ, cụ thể, mô tả HÌNH ẢNH cần thấy).
  Ví dụ tốt: "hands typing on laptop keyboard", "aerial view rice terraces vietnam".
  Ví dụ xấu: "success", "business", "technology".
- query_vi: cùng ý đó bằng tiếng Việt để người dùng đọc hiểu.
- reason: 1 câu tiếng Việt giải thích vì sao hình này khớp với lời nói."""


def broll_plan(segments: list[dict], settings: BrollSettings) -> list[dict]:
    """Chọn các vị trí nên chèn B-roll + từ khoá tìm hình đúng ngữ cảnh."""
    if not settings.enabled or not has_claude() or not segments:
        return []

    by_id = {s["id"]: s for s in segments}
    slots: list[dict] = []
    system = _BROLL_SYSTEM.format(max_slots=settings.max_clips)

    for start in range(0, len(segments), _MAX_SEGMENTS_PER_CALL):
        chunk = segments[start:start + _MAX_SEGMENTS_PER_CALL]
        user = "Transcript:\n\n" + _segments_as_text(chunk)
        result = _claude_json(system, user, _BROLL_SCHEMA)
        if not result:
            continue
        for item in result.get("slots", []):
            seg = by_id.get(item.get("segment_id"))
            query_en = (item.get("query_en") or "").strip()
            if not seg or not query_en:
                continue
            slots.append({
                "segment_id": seg["id"],
                "start": round(seg["start"], 3),
                "end": round(min(seg["end"], seg["start"] + settings.clip_len), 3),
                "query": query_en,
                "query_vi": (item.get("query_vi") or "").strip(),
                "reason": (item.get("reason") or "").strip(),
                "line": seg.get("text", ""),
            })

    return _space_out(slots, settings)


def _space_out(slots: list[dict], settings: BrollSettings) -> list[dict]:
    """Đảm bảo các đoạn B-roll cách nhau đủ xa và không vượt quá số lượng cho phép."""
    slots.sort(key=lambda s: s["start"])
    kept: list[dict] = []
    for slot in slots:
        if kept and slot["start"] - kept[-1]["end"] < settings.min_gap:
            continue
        kept.append(slot)
        if len(kept) >= settings.max_clips:
            break
    return kept


# ---------------------------------------------------------------------------
# 4. Chấm điểm độ khớp ngữ cảnh của các clip stock tải về
# ---------------------------------------------------------------------------

_RANK_SCHEMA = {
    "type": "object",
    "properties": {
        "best_index": {"type": "integer"},
        "score": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["best_index", "score", "reason"],
    "additionalProperties": False,
}

_RANK_SYSTEM = """Bạn là biên tập viên video. Người dùng đang nói một câu, và bạn có một danh sách
video stock ứng viên (kèm mô tả/tags tiếng Anh).

Chọn ĐÚNG MỘT clip minh hoạ sát nghĩa nhất với câu nói.
- score 0-100: mức độ khớp ngữ cảnh. Dưới 55 nghĩa là không clip nào thực sự hợp.
- Nếu tất cả đều chung chung hoặc lệch nghĩa, cứ cho score thấp — thà không chèn
  còn hơn chèn hình sai ngữ cảnh.
- reason: 1 câu tiếng Việt."""


def rank_broll_candidates(line: str, query: str, candidates: list[dict]) -> dict:
    """Trả về {"best_index": int, "score": int, "reason": str}."""
    if not candidates:
        return {"best_index": -1, "score": 0, "reason": "Không tìm được clip nào."}
    if not has_claude() or len(candidates) == 1:
        return {"best_index": 0, "score": 60, "reason": "Chọn kết quả khớp từ khoá tốt nhất."}

    listing = "\n".join(
        f"[{i}] nguồn={c.get('provider')} | mô tả: {c.get('description') or '(trống)'} "
        f"| tags: {c.get('tags') or '(trống)'} | dài {c.get('duration', 0):.0f}s"
        for i, c in enumerate(candidates)
    )
    user = (
        f'Câu người nói (tiếng Việt): "{line}"\n'
        f'Từ khoá đã dùng để tìm: "{query}"\n\n'
        f"Các clip ứng viên:\n{listing}"
    )
    result = _claude_json(_RANK_SYSTEM, user, _RANK_SCHEMA, max_tokens=2000)
    if not result:
        return {"best_index": 0, "score": 55, "reason": "Không chấm điểm được, lấy kết quả đầu."}

    idx = int(result.get("best_index", 0))
    if idx < 0 or idx >= len(candidates):
        idx = 0
    return {
        "best_index": idx,
        "score": int(result.get("score", 0)),
        "reason": result.get("reason", ""),
    }
