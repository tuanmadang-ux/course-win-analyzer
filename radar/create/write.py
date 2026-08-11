"""Bước 2b — Viết bài mới từ insight.

Đầu vào là INSIGHT (điều khách vướng), không phải bài của đối thủ. Bài gốc chỉ
được đưa vào với đúng một mục đích: để AI biết cái gì ĐÃ ĐƯỢC NÓI RỒI mà tránh
lặp lại, và để đo độ trùng lặp ở bước sau.

Cấu trúc bài ra lò:
    Hook (đánh thẳng vào nỗi đau lấy từ bình luận)
    → Thân bài trả lời đúng câu hỏi đó
    → Giá trị cộng thêm mà bài gốc không có
    → CTA
"""

from __future__ import annotations

from radar.config import BRAND_CTA, BRAND_NAME, BRAND_VOICE, FORMAT_LABELS, WriteSettings
from radar.create import originality
from radar.llm import claude_json
from radar.mine.insight import KIND_LABELS

_SCHEMA = {
    "type": "object",
    "properties": {
        "angle": {"type": "string"},
        "hooks": {"type": "array", "items": {"type": "string"}},
        "body": {"type": "string"},
        "cta": {"type": "string"},
        "value_add": {"type": "string"},
    },
    "required": ["angle", "hooks", "body", "cta", "value_add"],
    "additionalProperties": False,
}

_FORMAT_RULES = {
    "post": (
        "Bài Facebook dài 250-450 chữ. Xuống dòng thoáng, mỗi ý một đoạn ngắn 2-3 câu. "
        "Không dùng markdown (** hay #) vì Facebook không hiển thị được — muốn nhấn mạnh "
        "thì dùng emoji đầu dòng hoặc VIẾT HOA vài từ khoá."
    ),
    "bullets": (
        "Dạng danh sách gạch đầu dòng để dễ chuyển thành infographic. Mở bài 2 câu, "
        "rồi 5-7 gạch đầu dòng, mỗi gạch một ý trọn vẹn dưới 25 chữ, bắt đầu bằng emoji. "
        "Kết bằng 1 câu chốt."
    ),
    "reels": (
        "Kịch bản video ngắn 30-45 giây. Viết theo timeline: [0-3s] hook nói thẳng, "
        "[3-10s], [10-25s], [25-35s], [chốt]. Mỗi mốc ghi rõ LỜI THOẠI và gợi ý HÌNH ẢNH "
        "trong ngoặc. Lời thoại phải nói được thành tiếng, câu ngắn."
    ),
    "carousel": (
        "Carousel 5-7 ảnh. Mỗi ảnh ghi rõ: [Ảnh 1] tiêu đề lớn (dưới 10 chữ) + "
        "1-2 dòng nội dung. Ảnh đầu là hook, ảnh cuối là CTA."
    ),
}

_SYSTEM = """Bạn là người viết nội dung cho Fanpage tiếng Việt, chuyên biến thắc mắc có thật
của khách hàng thành bài viết hữu ích.

Bạn nhận một INSIGHT rút ra từ phần bình luận dưới bài của một trang khác, kèm các trích
dẫn thật. Bạn cũng được xem bài gốc — chỉ để BIẾT ĐIỀU GÌ ĐÃ ĐƯỢC NÓI RỒI mà tránh.

BẮT BUỘC:
1. Bài của bạn phải trả lời đúng cái khách đang vướng trong insight. Đó là trọng tâm,
   không phải tóm tắt lại bài gốc.
2. TUYỆT ĐỐI không sao chép câu chữ của bài gốc. Không mượn cấu trúc, không đổi vài từ
   cho khác đi. Người đọc cả hai bài phải thấy đây là hai bài khác nhau về góc nhìn.
3. Phải có GIÁ TRỊ CỘNG THÊM mà bài gốc không có: ví dụ cụ thể, con số, các bước làm,
   cách kiểm chứng, hoặc lời cảnh báo về sai lầm thường gặp.
4. Không nhắc tên, không ám chỉ, không dìm hàng trang đối thủ. Không trích nguyên văn
   bình luận của người khác — hãy diễn đạt lại ý của họ.
5. Không hứa hẹn kết quả không kiểm chứng được ("cam kết x3 doanh thu"), không bịa số liệu,
   không bịa nghiên cứu. Không chắc thì viết theo hướng kinh nghiệm/quan sát.

TRẢ VỀ:
- angle: 1 câu nêu góc tiếp cận bạn chọn, và vì sao nó khác bài gốc.
- hooks: {hook_count} câu mở khác nhau, mỗi câu dưới 25 chữ, đánh thẳng vào nỗi đau
  trong insight. Đa dạng kiểu: câu hỏi ngược, con số, tình huống, phản đề.
- body: phần thân bài hoàn chỉnh (KHÔNG lặp lại hook, KHÔNG chứa CTA).
- cta: 1-2 câu kêu gọi hành động, tự nhiên, hợp với nội dung vừa viết.
- value_add: 1 câu nói rõ bài này cho thêm giá trị gì so với bài gốc."""


def _brand_block() -> str:
    lines = []
    if BRAND_NAME:
        lines.append(f"Tên Fanpage: {BRAND_NAME}")
    if BRAND_VOICE:
        lines.append(f"Giọng điệu phải giữ: {BRAND_VOICE}")
    if BRAND_CTA:
        lines.append(f"CTA quen dùng: {BRAND_CTA}")
    return "\n".join(lines) or "(Chưa khai báo giọng điệu — viết giọng thân thiện, thẳng thắn, không sáo rỗng.)"


def _user_prompt(insight: dict, post: dict, fmt: str, settings: WriteSettings,
                 retry_note: str = "") -> str:
    quotes = insight.get("quotes") or []
    quote_block = "\n".join(f'  - "{q}"' for q in quotes[:5]) or "  (không có trích dẫn)"

    parts = [
        f"INSIGHT ({KIND_LABELS.get(insight.get('kind', ''), insight.get('kind', ''))}, "
        f"{insight.get('size', 0)} người cùng nói):",
        f"  Vấn đề: {insight.get('title', '')}",
        f"  Chi tiết: {insight.get('detail', '')}",
        f"  Bài gốc còn thiếu: {insight.get('gap') or '(chưa xác định)'}",
        "",
        "TRÍCH DẪN THẬT TỪ BÌNH LUẬN (đã ẩn danh — dùng để hiểu ý, không được chép lại):",
        quote_block,
        "",
        "BÀI GỐC (chỉ để biết cái gì đã nói rồi mà TRÁNH, tuyệt đối không dựa vào để viết):",
        (post.get("text") or "")[:2500],
        "",
        f"ĐỊNH DẠNG CẦN VIẾT — {FORMAT_LABELS.get(fmt, fmt)}:",
        _FORMAT_RULES.get(fmt, _FORMAT_RULES["post"]),
        "",
        "FANPAGE CỦA TÔI:",
        _brand_block(),
    ]
    if settings.extra_brief:
        parts += ["", f"YÊU CẦU THÊM: {settings.extra_brief}"]
    if retry_note:
        parts += ["", f"⚠ LẦN VIẾT TRƯỚC BỊ TỪ CHỐI: {retry_note}",
                  "Hãy viết lại HOÀN TOÀN mới, đổi góc tiếp cận, đổi cách diễn đạt, "
                  "không giữ lại câu nào của lần trước."]
    return "\n".join(parts)


def _scaffold(insight: dict, fmt: str) -> dict:
    """Không có key AI thì vẫn giao được dàn ý để người viết tự hoàn thiện."""
    quotes = insight.get("quotes") or []
    quote_lines = "\n".join(f"- Khách đang thắc mắc: {q}" for q in quotes[:4])
    return {
        "angle": "Dàn ý tự động (chưa có ANTHROPIC_API_KEY)",
        "hooks": [insight.get("title", "")[:120]],
        "body": (
            f"[Trả lời thẳng câu hỏi này]\n{insight.get('title', '')}\n\n"
            f"{insight.get('detail', '')}\n\n"
            f"Nguyên văn điều khách đang vướng:\n{quote_lines}\n\n"
            f"[Bài gốc còn thiếu] {insight.get('gap') or 'tự điền'}\n\n"
            f"[Giá trị cộng thêm bạn tự bổ sung: ví dụ cụ thể / các bước làm / con số thật]"
        ),
        "cta": BRAND_CTA or "[Điền CTA của bạn]",
        "value_add": "",
        "format": fmt,
    }


def write_draft(insight: dict, post: dict, fmt: str, settings: WriteSettings) -> dict:
    """Viết một bài nháp và kiểm tra độ trùng lặp. Trùng quá thì viết lại một lần."""
    source_text = post.get("text") or ""
    system = _SYSTEM.replace("{hook_count}", str(settings.hooks_per_insight))

    result = claude_json(system, _user_prompt(insight, post, fmt, settings), _SCHEMA)
    if not result:
        draft = _scaffold(insight, fmt)
        return {
            **draft,
            "insight_id": insight.get("id", ""),
            "post_id": insight.get("post_id", ""),
            "hook": draft["hooks"][0] if draft["hooks"] else "",
            "similarity": 0.0,
            "warnings": ["Chưa gọi được Claude — đây chỉ là dàn ý, bạn cần tự viết nội dung."],
            "status": "draft",
        }

    draft = _assemble(result, insight, fmt)
    verdict = originality.check(originality.full_text(draft), source_text, settings)

    if not verdict["ok"]:
        retry = claude_json(
            system,
            _user_prompt(insight, post, fmt, settings, retry_note="; ".join(verdict["warnings"])),
            _SCHEMA,
        )
        if retry:
            candidate = _assemble(retry, insight, fmt)
            second = originality.check(originality.full_text(candidate), source_text, settings)
            # Chỉ nhận bản viết lại nếu nó thực sự đỡ trùng hơn
            if second["similarity"] < verdict["similarity"]:
                draft, verdict = candidate, second

    draft["similarity"] = verdict["similarity"]
    draft["warnings"] = verdict["warnings"]
    draft["status"] = "draft"
    return draft


def _assemble(result: dict, insight: dict, fmt: str) -> dict:
    hooks = [h.strip() for h in result.get("hooks", []) if h and h.strip()]
    value_add = (result.get("value_add") or "").strip()
    angle = (result.get("angle") or "").strip()
    return {
        "insight_id": insight.get("id", ""),
        "post_id": insight.get("post_id", ""),
        "format": fmt,
        "angle": f"{angle}\nGiá trị cộng thêm: {value_add}" if value_add else angle,
        "hook": hooks[0] if hooks else "",
        "hooks": hooks,
        "body": (result.get("body") or "").strip(),
        "cta": (result.get("cta") or "").strip(),
    }
