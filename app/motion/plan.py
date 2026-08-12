"""Quyết định câu nào đáng có thẻ đồ hoạ, và thẻ đó ghi gì.

Điểm khác biệt so với B-roll stock: thẻ ở đây **lấy nội dung từ chính lời đang
nói**. Người nói "ba khoản làm bạn hết tiền" thì thẻ liệt kê đúng ba khoản đó,
chứ không phải một clip stock chung chung về tiền bạc.

Vì thế bước này bắt buộc phải có AI đọc transcript. Không có key thì trả về danh
sách rỗng — thà không chèn còn hơn chèn thẻ vô nghĩa.
"""

from __future__ import annotations

import logging

from app.motion import cards

log = logging.getLogger(__name__)

# Hai thẻ liên tiếp phải cách nhau ngần này giây, nếu không màn hình sẽ rối
MIN_GAP = 6.0
# Thẻ ngắn hơn ngần này thì người xem chưa kịp đọc
MIN_HOLD = 2.0
MAX_HOLD = 6.5

SYSTEM = """Bạn là người dựng video ngắn dọc cho khán giả Việt Nam.

Việc của bạn: đọc lời thoại và chọn ra vài chỗ đáng chèn MỘT THẺ ĐỒ HOẠ lên
màn hình để người xem nắm ý nhanh hơn.

Nguyên tắc bắt buộc:
- CHỈ chèn khi thẻ làm rõ thêm điều đang được nói. Không chèn để trang trí.
- Nội dung thẻ phải lấy từ chính lời thoại đó. Tuyệt đối không bịa số liệu,
  không thêm thông tin người nói không hề nói.
- Chữ trên thẻ phải NGẮN. Đây là chữ đọc lướt trên điện thoại, không phải đoạn văn.
- Thà chèn ít mà đúng còn hơn chèn nhiều."""


def _prompt(segments: list[dict], max_cards: int, duration: float) -> str:
    lines = "\n".join(
        f"[{i}] {s['start']:.1f}s–{s['end']:.1f}s: {s['text']}"
        for i, s in enumerate(segments)
    )
    return f"""Lời thoại của video (dài {duration:.0f} giây):

{lines}

Chọn tối đa {max_cards} chỗ để chèn thẻ. Các loại thẻ dùng được:

{cards.prompt_reference()}

Trả về JSON đúng dạng:
{{
  "cards": [
    {{
      "segment": <số thứ tự câu trong ngoặc vuông>,
      "type": "<một trong các loại trên>",
      "data": {{ ...các trường của loại đó... }},
      "reason": "vì sao chèn ở đây, một câu ngắn"
    }}
  ]
}}

Nếu không có chỗ nào thật sự đáng chèn, trả về {{"cards": []}}."""


def build(
    segments: list[dict],
    duration: float,
    max_cards: int = 4,
    ask_json=None,
) -> list[dict]:
    """Trả về danh sách thẻ đã kiểm tra và canh giờ.

    `ask_json` — hàm nhận (prompt, system) và trả về dict. Truyền vào để dùng
    được cả Gemini (trang tạo video) lẫn Claude (trang cắt video) mà module này
    không phải biết đang nói chuyện với ai.
    """
    if not segments or ask_json is None or max_cards <= 0:
        return []

    try:
        data = ask_json(_prompt(segments, max_cards, duration), SYSTEM)
    except Exception as exc:  # noqa: BLE001
        log.warning("Không lập được kế hoạch thẻ đồ hoạ (%s) — bỏ qua.", exc)
        return []

    raw = (data or {}).get("cards") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []

    planned: list[dict] = []
    for item in raw:
        card = _validate(item, segments)
        if card:
            planned.append(card)

    return _space_out(planned, duration, max_cards)


def _validate(item: object, segments: list[dict]) -> dict | None:
    if not isinstance(item, dict):
        return None

    try:
        index = int(item.get("segment"))
    except (TypeError, ValueError):
        return None
    if not 0 <= index < len(segments):
        return None

    card_type = str(item.get("type") or "").strip()
    data = cards.clean(card_type, item.get("data") or {})
    if data is None:
        log.info("Bỏ thẻ %r ở câu %d: dữ liệu không hợp lệ.", card_type, index)
        return None

    seg = segments[index]
    start = float(seg["start"])

    # Thẻ nên giữ qua hết câu đang nói, nhưng có trần để không dính sang ý sau
    hold = float(seg["end"]) - start
    hold = max(MIN_HOLD, min(hold + 0.6, MAX_HOLD))

    return {
        "segment": index,
        "type": card_type,
        "data": data,
        "reason": str(item.get("reason") or "").strip(),
        "start": round(start, 3),
        "duration": round(hold, 3),
        "line": seg["text"],
    }


def _space_out(planned: list[dict], duration: float, max_cards: int) -> list[dict]:
    """Bỏ thẻ chồng nhau, ép khoảng cách tối thiểu, cắt bớt nếu quá nhiều."""
    planned.sort(key=lambda c: c["start"])

    kept: list[dict] = []
    for card in planned:
        if kept and card["start"] - kept[-1]["start"] < MIN_GAP:
            continue
        # Không để thẻ tràn quá cuối video
        if card["start"] >= duration - 0.6:
            continue
        card["duration"] = round(min(card["duration"], duration - card["start"]), 3)
        if card["duration"] < 1.0:
            continue

        # `hook` chỉ có nghĩa ở đầu video; nơi khác thì đổi thành quote
        if card["type"] == "hook" and card["start"] > 4.0:
            card["type"] = "quote"
            card["data"] = {"text": card["data"].get("text", "").replace("*", "")}

        kept.append(card)
        if len(kept) >= max_cards:
            break

    return kept
