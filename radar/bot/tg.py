"""Client Telegram viết tay bằng httpx — không cần cài thêm thư viện bot nào.

Chỉ dùng long polling (getUpdates), nên không cần webhook, không cần ngrok,
không cần mở cổng. Cắm token vào là chạy được ngay từ máy ở nhà.
"""

from __future__ import annotations

import html
import logging
import time

import httpx

log = logging.getLogger(__name__)

API = "https://api.telegram.org"

# Telegram chặn tin nhắn quá 4096 ký tự; chừa chỗ cho thẻ HTML
MAX_CHARS = 3800
POLL_TIMEOUT = 50


def esc(text: object) -> str:
    """Bọc nội dung do người dùng gõ trước khi nhét vào HTML của Telegram."""
    return html.escape(str(text if text is not None else ""), quote=False)


def split_long(text: str) -> list[str]:
    """Cắt tin nhắn dài theo ranh giới dòng để không vỡ giữa câu."""
    if len(text) <= MAX_CHARS:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        # Một dòng dài hơn cả giới hạn thì buộc phải cắt cứng
        while len(line) > MAX_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:MAX_CHARS])
            line = line[MAX_CHARS:]
        if len(current) + len(line) + 1 > MAX_CHARS:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """Bàn phím inline: mỗi nút là (nhãn, dữ liệu callback ≤ 64 byte)."""
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row]
            for row in rows
        ]
    }


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str) -> None:
        if not token:
            raise TelegramError("Chưa có TELEGRAM_BOT_TOKEN trong .env.")
        self._base = f"{API}/bot{token}"
        self._client = httpx.Client(timeout=POLL_TIMEOUT + 15)

    # -- gọi API -----------------------------------------------------------

    def call(self, method: str, **params) -> dict:
        try:
            resp = self._client.post(f"{self._base}/{method}", json=params)
        except httpx.HTTPError as exc:
            raise TelegramError(f"Không gọi được Telegram: {exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise TelegramError(f"Telegram trả về dữ liệu lạ (HTTP {resp.status_code}).") from exc

        if not data.get("ok"):
            raise TelegramError(f"{data.get('description', 'lỗi không rõ')} "
                                f"(mã {data.get('error_code')})")
        return data.get("result")

    def me(self) -> dict:
        return self.call("getMe")

    # -- gửi tin -----------------------------------------------------------

    def send(self, chat_id: int, text: str, buttons: dict | None = None) -> int | None:
        """Gửi tin (tự cắt nếu dài). Nút chỉ gắn vào mảnh cuối."""
        parts = split_long(text)
        last_id = None
        for i, part in enumerate(parts):
            params = {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            }
            if buttons and i == len(parts) - 1:
                params["reply_markup"] = buttons
            try:
                last_id = (self.call("sendMessage", **params) or {}).get("message_id")
            except TelegramError as exc:
                log.warning("Gửi tin thất bại: %s", exc)
        return last_id

    def edit(self, chat_id: int, message_id: int, text: str, buttons: dict | None = None) -> None:
        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": split_long(text)[0],
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if buttons is not None:
            params["reply_markup"] = buttons
        try:
            self.call("editMessageText", **params)
        except TelegramError as exc:
            # Sửa lại đúng nội dung cũ thì Telegram báo lỗi — không phải chuyện gì
            if "not modified" not in str(exc).lower():
                log.warning("Sửa tin thất bại: %s", exc)

    def answer(self, callback_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])
        except TelegramError as exc:
            log.debug("answerCallbackQuery lỗi: %s", exc)

    def set_menu(self, commands: list[tuple[str, str]]) -> None:
        try:
            self.call("setMyCommands",
                      commands=[{"command": c, "description": d} for c, d in commands])
        except TelegramError as exc:
            log.warning("Không đặt được menu lệnh: %s", exc)

    # -- nhận tin ----------------------------------------------------------

    def poll(self, offset: int) -> tuple[list[dict], int]:
        """Lấy update mới. Trả về (danh sách update, offset kế tiếp)."""
        updates = self.call(
            "getUpdates",
            offset=offset,
            timeout=POLL_TIMEOUT,
            allowed_updates=["message", "callback_query"],
        ) or []
        for u in updates:
            offset = max(offset, u["update_id"] + 1)
        return updates, offset

    def drain_backlog(self) -> int:
        """Bỏ qua tin nhắn tồn từ lần chạy trước — tránh bot thức dậy là
        làm lại một loạt lệnh cũ."""
        try:
            updates = self.call("getUpdates", offset=-1, timeout=0) or []
        except TelegramError:
            return 0
        return updates[-1]["update_id"] + 1 if updates else 0

    def close(self) -> None:
        self._client.close()


def poll_forever(bot: Telegram, handle, stop=lambda: False) -> None:
    """Vòng lặp chính. Lỗi mạng thì lùi dần rồi thử lại, không chết bot."""
    offset = bot.drain_backlog()
    backoff = 1.0

    while not stop():
        try:
            updates, offset = bot.poll(offset)
            backoff = 1.0
        except TelegramError as exc:
            log.warning("Mất kết nối Telegram (%s) — thử lại sau %.0fs", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue

        for update in updates:
            try:
                handle(update)
            except Exception:  # noqa: BLE001 - một lệnh hỏng không được làm sập bot
                log.exception("Xử lý update lỗi")
