"""Bot Telegram điều khiển Radar đối thủ.

Chạy: python run_bot.py

Dùng chung SQLite với web app, nên bạn dán bài trên điện thoại lúc đang đi
đường, về nhà mở web lên là thấy y nguyên.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from radar import store
from radar.bot import access
from radar.bot.handlers import COMMANDS, MENU, Handlers
from radar.bot.tg import Telegram, poll_forever

log = logging.getLogger(__name__)

DENIED = ("Bot này đã có chủ rồi. Nếu đây là bot của bạn, xoá file "
          "data/radar/telegram_owner.json rồi bấm /start lại.")


class Bot:
    def __init__(self, token: str) -> None:
        self.tg = Telegram(token)
        self.handlers = Handlers(self.tg)
        # Đào và viết bài mất vài chục giây; làm ở luồng riêng để bot vẫn nghe lệnh
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="radar-bot")

    # -- phân loại update --------------------------------------------------

    def dispatch(self, update: dict) -> None:
        if "callback_query" in update:
            self._pool.submit(self._safe, self._on_callback, update["callback_query"])
        elif "message" in update:
            self._pool.submit(self._safe, self._on_message, update["message"])

    @staticmethod
    def _safe(fn, payload: dict) -> None:
        try:
            fn(payload)
        except Exception:  # noqa: BLE001 - một lệnh hỏng không được làm sập bot
            log.exception("Xử lý lệnh lỗi")

    def _allowed(self, chat_id: int, user: dict) -> bool:
        name = (user.get("username") or user.get("first_name") or "").strip()
        if access.allowed(chat_id, name):
            return True
        log.warning("Từ chối chat %s (%s)", chat_id, name)
        return False

    # -- tin nhắn ----------------------------------------------------------

    def _on_message(self, message: dict) -> None:
        chat_id = message["chat"]["id"]
        if not self._allowed(chat_id, message.get("from") or {}):
            self.tg.send(chat_id, DENIED)
            return

        text = (message.get("text") or message.get("caption") or "").strip()
        if not text:
            self.tg.send(chat_id, "Bot chỉ nhận chữ. Dán nội dung bài hoặc bình luận vào nhé.")
            return

        if text.startswith("/"):
            self._run_command(chat_id, text)
        else:
            self.handlers.on_text(chat_id, text)

    def _run_command(self, chat_id: int, text: str) -> None:
        head, _, args = text.partition(" ")
        name = head[1:].split("@", 1)[0].lower()   # /dao@ten_bot -> dao

        method = COMMANDS.get(name)
        if not method:
            self.tg.send(chat_id, f"Chưa có lệnh <code>/{name}</code>. Bấm /trogiup để xem danh sách.")
            return
        getattr(self.handlers, method)(chat_id, args.strip())

    # -- nút bấm -----------------------------------------------------------

    def _on_callback(self, query: dict) -> None:
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None:
            return
        if not self._allowed(chat_id, query.get("from") or {}):
            self.tg.answer(query["id"], "Không có quyền")
            return

        self.handlers.on_callback(
            chat_id, message.get("message_id"), query.get("data") or "", query["id"]
        )

    # -- vòng đời ----------------------------------------------------------

    def run(self) -> None:
        store.init_db()
        self.tg.set_menu(MENU)

        owner = access.owner_id()
        if owner:
            try:
                self.tg.send(owner, "📡 Radar đã bật lại. Bấm /trogiup nếu quên lệnh.")
            except Exception:  # noqa: BLE001 - báo hiệu thôi, hỏng cũng không sao
                log.debug("Không gửi được lời chào cho chủ bot")

        try:
            poll_forever(self.tg, self.dispatch)
        finally:
            self._pool.shutdown(wait=False)
            self.tg.close()
