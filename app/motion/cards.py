"""Khai báo các loại thẻ đồ hoạ và cách kiểm tra dữ liệu điền vào chúng.

Đây là nơi duy nhất mô tả "một thẻ gồm những trường gì". Cả prompt gửi cho AI,
cả bộ kiểm tra dữ liệu trả về, cả hai engine render đều đọc từ đây — nên thêm
một loại thẻ mới chỉ phải sửa một chỗ.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_ITEMS = 5


@dataclass(frozen=True)
class CardSpec:
    id: str
    label: str                       # mô tả cho AI biết khi nào nên dùng
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    limits: dict[str, int] = field(default_factory=dict)   # tên trường -> số ký tự tối đa


CARDS: dict[str, CardSpec] = {
    "stat": CardSpec(
        id="stat",
        label="Một con số hoặc một lượng cụ thể đang được nói tới "
              "(giá, phần trăm, số ngày, số khoản). Đừng dùng nếu câu không có số.",
        required=("value", "label"),
        optional=("note",),
        limits={"value": 14, "label": 44, "note": 60},
    ),
    "steps": CardSpec(
        id="steps",
        label="Một danh sách 2-5 ý mà người nói đang liệt kê ra "
              "(các bước, các lý do, các khoản mục).",
        required=("items",),
        optional=("title", "ordered"),
        limits={"title": 40, "items": 260},
    ),
    "quote": CardSpec(
        id="quote",
        label="Một câu chốt đáng nhớ, một nguyên tắc, hoặc lời trích dẫn.",
        required=("text",),
        optional=("who",),
        limits={"text": 110, "who": 40},
    ),
    "compare": CardSpec(
        id="compare",
        label="Đang so sánh hai cách làm, cái sai và cái đúng, trước và sau.",
        required=("bad_text", "good_text"),
        optional=("bad_label", "good_label"),
        limits={"bad_text": 60, "good_text": 60, "bad_label": 16, "good_label": 16},
    ),
    "hook": CardSpec(
        id="hook",
        label="Câu móc mở đầu, chỉ dùng cho 1-2 câu ĐẦU TIÊN của video. "
              "Bọc từ khoá cần nhấn trong dấu sao, ví dụ: mất *3 triệu* mỗi tháng.",
        required=("text",),
        optional=("kicker",),
        limits={"text": 80, "kicker": 26},
    ),
    "lower_third": CardSpec(
        id="lower_third",
        label="Thanh giới thiệu tên và vai trò người nói. Chỉ dùng một lần, ở đầu video.",
        required=("name",),
        optional=("role",),
        limits={"name": 30, "role": 44},
    ),
}


def prompt_reference() -> str:
    """Bảng mô tả các loại thẻ, nhúng vào prompt gửi AI."""
    lines = []
    for spec in CARDS.values():
        fields = ", ".join(spec.required)
        extra = f" (không bắt buộc: {', '.join(spec.optional)})" if spec.optional else ""
        lines.append(f'- "{spec.id}": {spec.label}\n  Trường: {fields}{extra}')
    return "\n".join(lines)


def clean(card_type: str, data: dict) -> dict | None:
    """Nắn dữ liệu AI trả về cho khớp khai báo. Trả None nếu không cứu được.

    Thà bỏ một thẻ còn hơn để nó render ra chữ tràn khung hoặc trống trơn.
    """
    spec = CARDS.get(card_type)
    if spec is None:
        return None

    out: dict[str, str] = {}
    for key in spec.required + spec.optional:
        raw = data.get(key)
        if raw is None:
            continue
        if key == "ordered":
            out[key] = "true" if raw not in (False, "false", "False", 0) else "false"
            continue
        if key == "items":
            out[key] = _join_items(raw, spec.limits.get("items", 260))
            continue

        text = " ".join(str(raw).split())
        limit = spec.limits.get(key)
        if limit and len(text) > limit:
            text = text[: limit - 1].rstrip() + "…"
        if text:
            out[key] = text

    if any(not out.get(key) for key in spec.required):
        return None
    return out


def _join_items(raw: object, limit: int) -> str:
    """Danh sách -> chuỗi ngăn bởi '|' (dạng mà template mong đợi)."""
    if isinstance(raw, str):
        parts = raw.split("|")
    elif isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        return ""

    items = [" ".join(str(p).split()) for p in parts]
    items = [i for i in items if i][:MAX_ITEMS]

    joined = "|".join(items)
    while len(joined) > limit and len(items) > 2:
        items.pop()
        joined = "|".join(items)
    return joined
