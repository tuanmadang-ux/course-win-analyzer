"""Tìm và tải B-roll từ kho video stock miễn phí (Pexels, Pixabay)."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import httpx

from app.config import BROLL_CACHE_DIR, PEXELS_API_KEY, PIXABAY_API_KEY

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


# ---------------------------------------------------------------------------
# Tìm kiếm
# ---------------------------------------------------------------------------


def _pexels_search(query: str, limit: int) -> list[dict]:
    if not PEXELS_API_KEY:
        return []
    try:
        resp = httpx.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": min(limit, 20), "size": "medium"},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Pexels lỗi cho '%s': %s", query, exc)
        return []

    out: list[dict] = []
    for v in data.get("videos", []):
        files = [
            f for f in v.get("video_files", [])
            if f.get("file_type") == "video/mp4" and f.get("link")
        ]
        if not files:
            continue
        # Ưu tiên bản có chiều cao gần 1080 nhất mà không quá nặng
        files.sort(key=lambda f: abs((f.get("height") or 0) - 1080))
        best = files[0]
        # Slug trong URL chính là mô tả nội dung clip trên Pexels
        slug = re.sub(r"[-/]+", " ", (v.get("url") or "").rstrip("/").split("/")[-1])
        slug = re.sub(r"\s*\d+\s*$", "", slug).strip()
        out.append({
            "provider": "pexels",
            "id": str(v.get("id")),
            "description": slug,
            "tags": slug,
            "duration": float(v.get("duration") or 0),
            "width": best.get("width") or 0,
            "height": best.get("height") or 0,
            "download_url": best["link"],
            "preview": v.get("image"),
            "credit": (v.get("user") or {}).get("name", ""),
            "page": v.get("url"),
        })
    return out


def _pixabay_search(query: str, limit: int) -> list[dict]:
    if not PIXABAY_API_KEY:
        return []
    try:
        resp = httpx.get(
            "https://pixabay.com/api/videos/",
            params={"key": PIXABAY_API_KEY, "q": query, "per_page": min(max(limit, 3), 20)},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Pixabay lỗi cho '%s': %s", query, exc)
        return []

    out: list[dict] = []
    for hit in data.get("hits", []):
        videos = hit.get("videos") or {}
        best = videos.get("large") or videos.get("medium") or videos.get("small")
        if not best or not best.get("url"):
            continue
        tags = hit.get("tags") or ""
        out.append({
            "provider": "pixabay",
            "id": str(hit.get("id")),
            "description": tags,
            "tags": tags,
            "duration": float(hit.get("duration") or 0),
            "width": best.get("width") or 0,
            "height": best.get("height") or 0,
            "download_url": best["url"],
            "preview": (videos.get("tiny") or {}).get("thumbnail") or hit.get("pageURL"),
            "credit": hit.get("user", ""),
            "page": hit.get("pageURL"),
        })
    return out


def search_candidates(query: str, limit: int = 6, min_duration: float = 3.0) -> list[dict]:
    """Gộp kết quả từ mọi nguồn đang có key."""
    results = _pexels_search(query, limit) + _pixabay_search(query, limit)
    results = [r for r in results if r["duration"] >= min_duration]
    # Ưu tiên clip có độ phân giải cao
    results.sort(key=lambda r: (r.get("height") or 0), reverse=True)
    return results[:limit]


# ---------------------------------------------------------------------------
# Tải về (có cache theo provider + id)
# ---------------------------------------------------------------------------


def download_candidate(candidate: dict) -> Path | None:
    key = f"{candidate['provider']}_{candidate['id']}"
    safe = hashlib.sha1(key.encode()).hexdigest()[:16]
    dest = BROLL_CACHE_DIR / f"{candidate['provider']}_{safe}.mp4"
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest

    try:
        with httpx.stream("GET", candidate["download_url"], timeout=_TIMEOUT, follow_redirects=True) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_bytes(chunk_size=1 << 16):
                    fh.write(chunk)
            tmp.replace(dest)
        return dest
    except Exception as exc:  # noqa: BLE001
        log.warning("Tải B-roll thất bại (%s): %s", candidate.get("page"), exc)
        return None


def stock_available() -> bool:
    return bool(PEXELS_API_KEY or PIXABAY_API_KEY)
