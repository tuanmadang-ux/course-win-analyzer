"""Chốt chặn chống "xào" quá tay.

"Xào lại" mà giữ nguyên câu chữ của người ta thì vừa dính bản quyền, vừa bị
thuật toán coi là nội dung trùng lặp và bóp tiếp cận — mất cả chì lẫn chài.
Nên mọi bài do AI viết đều phải qua hai phép đo trước khi được đưa cho người duyệt:

  1. Độ trùng cụm 5 tiếng — bài mới lấy lại bao nhiêu phần trăm cách diễn đạt của bài gốc.
  2. Chuỗi giống hệt dài nhất — có câu nào bị bê nguyên xi sang không.

Vượt ngưỡng thì bài bị gắn cờ, hiện cảnh báo đỏ trên giao diện và KHÔNG cho
lên lịch đăng cho tới khi người viết sửa lại.
"""

from __future__ import annotations

from radar.config import WriteSettings
from radar.mine.text import longest_common_run, shingles


def similarity(new_text: str, source_text: str) -> float:
    """Bao nhiêu phần cách diễn đạt của bài mới là lấy lại từ bài gốc (0..1).

    Dùng tỉ lệ chứa (containment) chứ không phải Jaccard: bài mới thường ngắn
    hơn bài gốc nhiều, Jaccard sẽ luôn cho số đẹp và bỏ lọt bài chép.
    """
    new_grams = shingles(new_text, 5)
    src_grams = shingles(source_text, 5)
    if not new_grams or not src_grams:
        return 0.0
    return len(new_grams & src_grams) / len(new_grams)


def check(new_text: str, source_text: str, settings: WriteSettings) -> dict:
    """Trả về {similarity, common_run, ok, warnings}."""
    sim = similarity(new_text, source_text)
    run = longest_common_run(new_text, source_text)

    warnings: list[str] = []
    if sim > settings.max_similarity:
        warnings.append(
            f"Trùng {sim * 100:.0f}% cách diễn đạt với bài gốc "
            f"(ngưỡng {settings.max_similarity * 100:.0f}%). Viết lại bằng chữ của bạn."
        )
    if run > settings.max_common_run:
        warnings.append(
            f"Có đoạn {run} chữ giống hệt bài gốc. Diễn đạt lại đoạn đó trước khi đăng."
        )

    return {
        "similarity": round(sim, 4),
        "common_run": run,
        "ok": not warnings,
        "warnings": warnings,
    }


def full_text(draft: dict) -> str:
    """Ghép hook + thân + CTA để đo và để đăng."""
    parts = [draft.get("hook", ""), draft.get("body", ""), draft.get("cta", "")]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())
