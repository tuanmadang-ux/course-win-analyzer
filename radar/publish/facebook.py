"""Graph API — CHỈ dùng cho Fanpage của chính bạn.

Đăng bài, hẹn giờ, và đọc chỉ số bài đã đăng. Token ở đây là Page Access Token
của trang bạn quản trị, lấy qua Meta for Developers. Không có phần nào trong
file này chạm tới trang của người khác.
"""

from __future__ import annotations

import logging

import httpx

from radar.config import FB_PAGE_ID, FB_PAGE_TOKEN, GRAPH_BASE, has_page

log = logging.getLogger(__name__)

TIMEOUT = 30.0

# Facebook bắt bài hẹn giờ phải cách hiện tại tối thiểu 10 phút, tối đa 6 tháng
MIN_LEAD_SECONDS = 15 * 60
MAX_LEAD_SECONDS = 180 * 86400


class GraphError(RuntimeError):
    pass


def _require_page() -> None:
    if not has_page():
        raise GraphError("Chưa có FB_PAGE_ID / FB_PAGE_TOKEN trong .env.")


def _request(method: str, path: str, **params) -> dict:
    url = f"{GRAPH_BASE}/{path.lstrip('/')}"
    params["access_token"] = FB_PAGE_TOKEN
    try:
        resp = httpx.request(method, url, params=params, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise GraphError(f"Không gọi được Facebook: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise GraphError(f"Facebook trả về dữ liệu lạ (HTTP {resp.status_code}).") from exc

    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise GraphError(f"{err.get('message', 'Lỗi không rõ')} (mã {err.get('code')})")
    if resp.status_code >= 400:
        raise GraphError(f"Facebook trả lỗi {resp.status_code}.")
    return data


def publish(message: str, scheduled_at: float | None = None) -> dict:
    """Đăng ngay (scheduled_at=None) hoặc hẹn giờ. Trả về {'id': '<page>_<post>'}."""
    _require_page()
    if not message.strip():
        raise GraphError("Nội dung bài đang trống.")

    params: dict = {"message": message}
    if scheduled_at:
        params.update({"published": "false", "scheduled_publish_time": int(scheduled_at)})

    data = _request("POST", f"{FB_PAGE_ID}/feed", **params)
    if "id" not in data:
        raise GraphError("Facebook không trả về id bài viết.")
    return data


def post_metrics(post_id: str) -> dict:
    """Chỉ số của một bài đã đăng. Thiếu quyền đọc insights thì vẫn lấy được
    lượt tương tác cơ bản."""
    _require_page()

    fields = ("shares,reactions.summary(true).limit(0),"
              "comments.summary(true).limit(0),created_time")
    basic = _request("GET", post_id, fields=fields)

    reactions = (basic.get("reactions") or {}).get("summary", {}).get("total_count", 0)
    comments = (basic.get("comments") or {}).get("summary", {}).get("total_count", 0)
    shares = (basic.get("shares") or {}).get("count", 0)

    reach = impressions = clicks = 0
    try:
        ins = _request("GET", f"{post_id}/insights",
                       metric="post_impressions,post_impressions_unique,post_clicks")
        for row in ins.get("data", []):
            values = row.get("values") or [{}]
            value = values[0].get("value", 0)
            if row.get("name") == "post_impressions_unique":
                reach = int(value or 0)
            elif row.get("name") == "post_impressions":
                impressions = int(value or 0)
            elif row.get("name") == "post_clicks":
                clicks = int(value or 0)
    except GraphError as exc:
        log.info("Không đọc được insights của %s (%s) — dùng tương tác cơ bản.", post_id, exc)

    engaged = reactions + comments + shares + clicks
    base = reach or impressions
    return {
        "reach": reach,
        "impressions": impressions,
        "reactions": reactions,
        "comments": comments,
        "shares": shares,
        "clicks": clicks,
        "engagement_rate": round(engaged / base, 4) if base else 0.0,
        "created_time": basic.get("created_time", ""),
    }


def recent_page_posts(limit: int = 50) -> list[dict]:
    """Bài gần đây của TRANG BẠN — dùng để tính khung giờ vàng thật của trang."""
    _require_page()
    fields = ("created_time,message,shares,"
              "reactions.summary(true).limit(0),comments.summary(true).limit(0)")
    data = _request("GET", f"{FB_PAGE_ID}/posts", fields=fields, limit=min(limit, 100))

    out = []
    for item in data.get("data", []):
        out.append({
            "id": item.get("id", ""),
            "created_time": item.get("created_time", ""),
            "reactions": (item.get("reactions") or {}).get("summary", {}).get("total_count", 0),
            "comments": (item.get("comments") or {}).get("summary", {}).get("total_count", 0),
            "shares": (item.get("shares") or {}).get("count", 0),
        })
    return out


def page_name() -> str:
    try:
        return _request("GET", FB_PAGE_ID, fields="name").get("name", "")
    except GraphError:
        return ""
