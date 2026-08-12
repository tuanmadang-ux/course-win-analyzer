"""Nối kế hoạch thẻ -> render từng thẻ -> chồng lên video, có báo tiến độ.

Tách riêng khỏi `app/avatar/service.py` để trang Cắt video dùng lại được y hệt:
cả hai đều chỉ có một danh sách câu kèm mốc thời gian và một file video nền.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from app.config import AvatarSettings, RenderSettings
from app.motion import cards as card_specs
from app.motion import engine, overlay, plan

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


def decorate(
    base: Path,
    segments: list[dict],
    duration: float,
    work_dir: Path,
    settings: AvatarSettings,
    render: RenderSettings,
    ask_json: Callable | None,
    on_progress: ProgressFn | None = None,
) -> dict:
    """Lập kế hoạch, dựng thẻ, chồng lên `base`.

    Trả về {"video": Path, "cards": [...], "engine": str}. Luôn trả về một video
    dùng được — mọi trục trặc chỉ làm mất thẻ, không làm mất thành phẩm.
    """
    empty = {"video": base, "cards": [], "engine": "off"}

    if not settings.motion:
        return empty

    try:
        chosen = engine.resolve(settings.motion_engine)
    except engine.MotionError as exc:
        log.warning("Không dùng được engine đồ hoạ (%s) — bỏ qua thẻ.", exc)
        return empty

    if chosen == "off":
        return empty

    if ask_json is None:
        log.info("Không có AI để chọn vị trí thẻ — bỏ qua thẻ đồ hoạ.")
        return empty

    if on_progress:
        on_progress(0.05, "Chọn chỗ đáng chèn thẻ đồ hoạ…")

    planned = plan.build(
        segments, duration, max_cards=settings.motion_max_cards, ask_json=ask_json
    )
    if not planned:
        log.info("AI không tìm được chỗ nào đáng chèn thẻ.")
        return {**empty, "engine": chosen}

    clips_dir = work_dir / "motion"
    rendered: list[dict] = []

    for i, card in enumerate(planned):
        if on_progress:
            on_progress(
                0.1 + 0.75 * (i / len(planned)),
                f"Dựng thẻ {i + 1}/{len(planned)} ({card['type']})",
            )
        dest = clips_dir / f"card_{i:02d}_{card['type']}.mov"
        try:
            engine.render_card(chosen, card["type"], card["data"], dest)
        except engine.MotionError as exc:
            # Một thẻ hỏng không nên giết cả video — bỏ thẻ đó, giữ các thẻ còn lại
            log.warning("Thẻ %d (%s) dựng lỗi: %s", i, card["type"], exc)
            continue
        rendered.append({**card, "clip": str(dest)})

    if not rendered:
        return {**empty, "engine": chosen}

    if on_progress:
        on_progress(0.9, f"Chồng {len(rendered)} thẻ lên video…")

    try:
        out = overlay.apply(
            base,
            [{"clip": c["clip"], "start": c["start"], "duration": c["duration"]} for c in rendered],
            work_dir / "with_motion.mp4",
            render,
            duration,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Chồng thẻ thất bại (%s) — giữ bản không thẻ.", exc)
        return {**empty, "engine": chosen}

    overlay.contact_sheet([Path(c["clip"]) for c in rendered], work_dir / "motion_preview.jpg")

    return {
        "video": out,
        "engine": chosen,
        "cards": [
            {k: v for k, v in c.items() if k != "clip"} | {"clip_name": Path(c["clip"]).name}
            for c in rendered
        ],
    }


def available_types() -> list[dict]:
    """Danh sách loại thẻ, cho giao diện hiển thị."""
    return [
        {"id": spec.id, "label": spec.label.split(".")[0]}
        for spec in card_specs.CARDS.values()
    ]
