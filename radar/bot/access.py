"""Khoá quyền ra lệnh.

Token bot không phải là bí mật tuyệt đối: ai biết tên bot cũng nhắn được cho
nó. Mà bot này thì đăng bài lên Fanpage của bạn và tiêu tiền API của bạn — nên
phải chốt lại xem AI được phép sai khiến nó.

Hai cách, cách nào cũng được:
  * Điền TELEGRAM_ALLOWED_IDS trong .env — chỉ những id đó ra lệnh được.
  * Để trống: người bấm /start ĐẦU TIÊN thành chủ bot, ghi vào
    data/radar/telegram_owner.json, từ đó khoá lại. Muốn đổi chủ thì xoá file.
"""

from __future__ import annotations

import json
import logging

from radar.config import OWNER_PATH, TELEGRAM_ALLOWED_IDS

log = logging.getLogger(__name__)


def _stored_owner() -> int | None:
    if not OWNER_PATH.exists():
        return None
    try:
        return int(json.loads(OWNER_PATH.read_text(encoding="utf-8"))["chat_id"])
    except (ValueError, KeyError, OSError):
        return None


def _remember(chat_id: int, name: str) -> None:
    OWNER_PATH.write_text(
        json.dumps({"chat_id": chat_id, "name": name}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Đã ghi nhận chủ bot: %s (id %s)", name, chat_id)


def allowed(chat_id: int, name: str = "") -> bool:
    """Người này có quyền ra lệnh không? Lần đầu thì tự nhận chủ."""
    if TELEGRAM_ALLOWED_IDS:
        return chat_id in TELEGRAM_ALLOWED_IDS

    owner = _stored_owner()
    if owner is None:
        _remember(chat_id, name)
        return True
    return chat_id == owner


def owner_id() -> int | None:
    return TELEGRAM_ALLOWED_IDS[0] if TELEGRAM_ALLOWED_IDS else _stored_owner()
