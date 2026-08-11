#!/usr/bin/env python3
"""Bật bot Telegram điều khiển Radar. Chạy: python run_bot.py"""

from __future__ import annotations

import logging
import sys

from radar.bot import Bot
from radar.bot.access import owner_id
from radar.bot.tg import TelegramError
from radar.config import (
    TELEGRAM_ALLOWED_IDS,
    TELEGRAM_BOT_TOKEN,
    has_apify,
    has_claude,
    has_page,
)

SETUP = """
  Chưa có TELEGRAM_BOT_TOKEN. Lấy trong 1 phút:

    1. Mở Telegram, nhắn cho @BotFather
    2. Gõ  /newbot  rồi đặt tên
    3. Copy dãy token nó đưa
    4. Dán vào file .env:   TELEGRAM_BOT_TOKEN=123456:ABC...
    5. Chạy lại lệnh này, rồi bấm /start trong chat với bot của bạn
"""


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 62)
    print("  RADAR ĐỐI THỦ — ra lệnh qua Telegram")
    print("=" * 62)

    if not TELEGRAM_BOT_TOKEN:
        print(SETUP)
        return 1

    try:
        bot = Bot(TELEGRAM_BOT_TOKEN)
        me = bot.tg.me()
    except TelegramError as exc:
        print(f"\n  ✗ Không kết nối được Telegram: {exc}")
        print("    Kiểm tra lại TELEGRAM_BOT_TOKEN trong .env và mạng của máy.\n")
        return 1

    print(f"  ✓ Bot: @{me.get('username')}")
    print(f"  {'✓' if has_claude() else '·'} Claude "
          f"{'(đào insight + viết bài)' if has_claude() else '(chưa có key — chỉ ra dàn ý)'}")
    print(f"  {'✓' if has_apify() else '·'} Apify")
    print(f"  {'✓' if has_page() else '·'} Fanpage "
          f"{'(đăng được từ điện thoại)' if has_page() else '(chưa nối — duyệt xong copy đăng tay)'}")

    if TELEGRAM_ALLOWED_IDS:
        print(f"  🔒 Chỉ nhận lệnh từ id: {', '.join(str(i) for i in TELEGRAM_ALLOWED_IDS)}")
    elif owner_id():
        print(f"  🔒 Chủ bot đã khoá ở id {owner_id()}")
    else:
        print("  🔓 Chưa có chủ — người bấm /start ĐẦU TIÊN sẽ thành chủ bot")

    print(f"\n  Mở Telegram, tìm @{me.get('username')}, bấm /start")
    print("  Dừng bằng Ctrl+C\n")

    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n  Đã dừng bot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
