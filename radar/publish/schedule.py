"""Khung giờ vàng + xếp lịch đăng.

Khung giờ vàng lấy từ chính dữ liệu trang BẠN (bài nào đăng giờ nào thì tương
tác ra sao), chứ không dùng "giờ vàng" chung chung trên mạng. Trang chưa đủ
bài để tính thì mới rơi về mốc mặc định của thị trường Việt Nam.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from radar.config import TZ_OFFSET_HOURS
from radar.publish import facebook

log = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=TZ_OFFSET_HOURS))

# Mốc mặc định khi trang chưa đủ dữ liệu (giờ địa phương → trọng số 0..1)
DEFAULT_HOURS = {6: 0.35, 7: 0.5, 8: 0.4, 11: 0.75, 12: 0.85, 13: 0.6,
                 17: 0.55, 19: 0.9, 20: 1.0, 21: 0.85, 22: 0.6}

MIN_POSTS_FOR_STATS = 8
MIN_GAP_HOURS = 4.0
LEAD_MINUTES = 20


def _engagement(post: dict) -> float:
    """Chia sẻ đáng giá hơn tim, bình luận đáng giá hơn tim."""
    return post.get("reactions", 0) + 2 * post.get("comments", 0) + 3 * post.get("shares", 0)


def golden_hours() -> dict:
    """Trả về {hours: {giờ: trọng số}, source: 'page'|'default', samples: n}."""
    try:
        posts = facebook.recent_page_posts(limit=100)
    except Exception as exc:  # noqa: BLE001
        log.info("Chưa lấy được bài của trang (%s) — dùng khung giờ mặc định.", exc)
        posts = []

    buckets: dict[int, list[float]] = defaultdict(list)
    for post in posts:
        created = post.get("created_time")
        if not created:
            continue
        try:
            dt = datetime.fromisoformat(str(created).replace("Z", "+00:00")).astimezone(TZ)
        except ValueError:
            continue
        buckets[dt.hour].append(_engagement(post))

    total = sum(len(v) for v in buckets.values())
    if total < MIN_POSTS_FOR_STATS:
        return {"hours": dict(DEFAULT_HOURS), "source": "default", "samples": total}

    averages = {h: sum(v) / len(v) for h, v in buckets.items() if v}
    peak = max(averages.values()) or 1.0
    hours = {h: round(v / peak, 3) for h, v in averages.items() if v / peak >= 0.3}
    if not hours:
        return {"hours": dict(DEFAULT_HOURS), "source": "default", "samples": total}
    return {"hours": hours, "source": "page", "samples": total}


def _candidates(hours: dict[int, float], start: datetime, days: int) -> list[tuple[datetime, float]]:
    out = []
    for day in range(days + 1):
        base = (start + timedelta(days=day)).replace(minute=0, second=0, microsecond=0)
        for hour, weight in hours.items():
            slot = base.replace(hour=hour)
            if slot > start:
                out.append((slot, weight))
    return sorted(out)


def next_slot(taken: list[float], now: float | None = None,
              hours: dict[int, float] | None = None) -> float:
    """Khung giờ tốt gần nhất chưa bị bài khác chiếm."""
    now_dt = datetime.fromtimestamp(now, TZ) if now else datetime.now(TZ)
    earliest = now_dt + timedelta(minutes=LEAD_MINUTES)
    weights = hours or golden_hours()["hours"]

    free = []
    for slot, weight in _candidates(weights, earliest, days=7):
        ts = slot.timestamp()
        if any(abs(ts - t) < MIN_GAP_HOURS * 3600 for t in taken):
            continue
        free.append((slot, weight, ts))

    if not free:
        return (earliest + timedelta(hours=MIN_GAP_HOURS)).timestamp()

    # Trong 48 giờ tới thì ưu tiên giờ mạnh nhất; xa hơn thì lấy sớm nhất
    soon = [f for f in free if f[2] - earliest.timestamp() <= 48 * 3600]
    pool = soon or free[:1]
    best = max(pool, key=lambda f: (f[1], -f[2]))
    return best[2]


def describe(ts: float) -> str:
    days = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
    dt = datetime.fromtimestamp(ts, TZ)
    return f"{days[dt.weekday()]} {dt:%d/%m} lúc {dt:%H:%M}"
