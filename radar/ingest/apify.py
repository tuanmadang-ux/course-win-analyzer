"""Thu thập tự động qua Apify — dịch vụ scraping thương mại bạn tự đăng ký.

Hệ thống này KHÔNG tự đăng nhập Facebook, không mượn cookie, không né giới hạn
tần suất. Nó chỉ gọi API công khai của Apify bằng token của chính bạn, để chạy
actor mà bạn đã chọn. Hạn mức, chi phí và việc tuân thủ điều khoản nền tảng
thuộc về tài khoản Apify của bạn.

Muốn dùng nhà cung cấp khác? Viết một hàm `fetch_posts(target, limit)` trả về
list[dict] rồi đăng ký trong radar/ingest/__init__.py — phần còn lại chạy y nguyên.
"""

from __future__ import annotations

import json
import logging

import httpx

from radar.config import (
    APIFY_ACTOR_COMMENTS,
    APIFY_ACTOR_POSTS,
    APIFY_COMMENTS_INPUT,
    APIFY_POSTS_INPUT,
    APIFY_TOKEN,
)

log = logging.getLogger(__name__)

API = "https://api.apify.com/v2"
RUN_TIMEOUT = 600  # giây — actor quét fanpage lớn có thể chạy vài phút


class ApifyError(RuntimeError):
    pass


def _actor_path(actor: str) -> str:
    """Apify nhận cả 'user/actor' lẫn 'user~actor'; API dùng dạng có dấu ~."""
    return actor.strip().replace("/", "~")


def _render_input(template: str, target: str, limit: int) -> dict:
    """Đổ target/limit vào mẫu JSON đầu vào của actor."""
    try:
        filled = template.replace("{target}", json.dumps(target)[1:-1]).replace("{limit}", str(limit))
        data = json.loads(filled)
    except json.JSONDecodeError as exc:
        raise ApifyError(f"Mẫu đầu vào cho actor không phải JSON hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise ApifyError("Mẫu đầu vào cho actor phải là một object JSON.")
    return data


def _run_actor(actor: str, payload: dict) -> list[dict]:
    url = f"{API}/acts/{_actor_path(actor)}/run-sync-get-dataset-items"
    try:
        resp = httpx.post(
            url,
            params={"token": APIFY_TOKEN, "timeout": RUN_TIMEOUT},
            json=payload,
            timeout=RUN_TIMEOUT + 30,
        )
    except httpx.HTTPError as exc:
        raise ApifyError(f"Không gọi được Apify: {exc}") from exc

    if resp.status_code == 401:
        raise ApifyError("APIFY_TOKEN sai hoặc hết hạn.")
    if resp.status_code == 404:
        raise ApifyError(f"Không tìm thấy actor “{actor}”. Kiểm tra lại tên trong .env.")
    if resp.status_code == 402:
        raise ApifyError("Tài khoản Apify hết hạn mức. Nạp thêm hoặc giảm số bài mỗi lần quét.")
    if resp.status_code >= 400:
        raise ApifyError(f"Apify trả lỗi {resp.status_code}: {resp.text[:300]}")

    try:
        items = resp.json()
    except ValueError as exc:
        raise ApifyError("Apify trả về dữ liệu không phải JSON.") from exc

    if isinstance(items, dict):
        items = items.get("items") or items.get("data") or []
    return [i for i in items if isinstance(i, dict)]


def available() -> dict:
    return {
        "token": bool(APIFY_TOKEN),
        "posts_actor": bool(APIFY_ACTOR_POSTS),
        "comments_actor": bool(APIFY_ACTOR_COMMENTS),
    }


def fetch_posts(target: str, limit: int = 30) -> list[dict]:
    """Lấy danh sách bài gần đây của một trang."""
    if not APIFY_TOKEN:
        raise ApifyError("Chưa có APIFY_TOKEN trong .env.")
    if not APIFY_ACTOR_POSTS:
        raise ApifyError("Chưa khai báo APIFY_ACTOR_POSTS trong .env.")
    if not target:
        raise ApifyError("Chưa có link trang cần quét.")
    return _run_actor(APIFY_ACTOR_POSTS, _render_input(APIFY_POSTS_INPUT, target, limit))


def fetch_comments(post_url: str, limit: int = 200) -> list[dict]:
    """Lấy bình luận của một bài. Không khai báo actor thì bỏ qua, không làm hỏng luồng."""
    if not APIFY_TOKEN or not APIFY_ACTOR_COMMENTS or not post_url:
        return []
    try:
        return _run_actor(APIFY_ACTOR_COMMENTS, _render_input(APIFY_COMMENTS_INPUT, post_url, limit))
    except ApifyError as exc:
        log.warning("Lấy bình luận thất bại cho %s: %s", post_url, exc)
        return []
