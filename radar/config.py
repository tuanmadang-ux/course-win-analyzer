"""Cấu hình Radar đối thủ: đường dẫn, khoá API, ngưỡng lọc & ngưỡng chống trùng lặp."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- Thư mục làm việc -------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "data")
RADAR_DIR = DATA_DIR / "radar"
IMPORT_DIR = RADAR_DIR / "imports"
DB_PATH = RADAR_DIR / "radar.db"

for _d in (RADAR_DIR, IMPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Khoá API ---------------------------------------------------------------
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
WRITER_MODEL = os.getenv("WRITER_MODEL", os.getenv("ANALYSIS_MODEL", "claude-opus-5")).strip()

# Apify — dịch vụ thu thập dữ liệu thương mại. Bạn tự đăng ký, tự chịu hạn mức.
APIFY_TOKEN = (os.getenv("APIFY_TOKEN") or "").strip()
APIFY_ACTOR_POSTS = (os.getenv("APIFY_ACTOR_POSTS") or "").strip()
APIFY_ACTOR_COMMENTS = (os.getenv("APIFY_ACTOR_COMMENTS") or "").strip()

# Mỗi actor có schema đầu vào riêng. Hai mẫu dưới hợp với các actor phổ biến;
# actor khác thì sửa lại ở .env. `{target}` và `{limit}` được thay lúc chạy.
APIFY_POSTS_INPUT = (os.getenv("APIFY_POSTS_INPUT")
                     or '{"startUrls":[{"url":"{target}"}],"resultsLimit":{limit}}').strip()
APIFY_COMMENTS_INPUT = (os.getenv("APIFY_COMMENTS_INPUT")
                        or '{"startUrls":[{"url":"{target}"}],"resultsLimit":{limit}}').strip()

# Meta Graph API — CHỈ dùng cho Fanpage CỦA BẠN (đăng bài + đọc chỉ số).
FB_PAGE_ID = (os.getenv("FB_PAGE_ID") or "").strip()
FB_PAGE_TOKEN = (os.getenv("FB_PAGE_TOKEN") or "").strip()
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v21.0").strip()
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# --- Giọng điệu Fanpage của bạn --------------------------------------------
BRAND_NAME = (os.getenv("BRAND_NAME") or "").strip()
BRAND_VOICE = (os.getenv("BRAND_VOICE") or "").strip()
BRAND_CTA = (os.getenv("BRAND_CTA") or "").strip()

RADAR_PORT = int(os.getenv("RADAR_PORT", "8010"))

# --- Ra lệnh qua Telegram ---------------------------------------------------
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
# Để trống thì người bấm /start đầu tiên trở thành chủ bot, khoá luôn từ đó.
TELEGRAM_ALLOWED_IDS = tuple(
    int(x) for x in (os.getenv("TELEGRAM_ALLOWED_IDS") or "").replace(" ", "").split(",")
    if x.lstrip("-").isdigit()
)
OWNER_PATH = RADAR_DIR / "telegram_owner.json"

# Múi giờ để tính khung giờ vàng (số giờ lệch so với UTC). VN = +7.
TZ_OFFSET_HOURS = float(os.getenv("TZ_OFFSET_HOURS", "7"))


def has_claude() -> bool:
    return bool(ANTHROPIC_API_KEY)


def has_apify() -> bool:
    return bool(APIFY_TOKEN)


def has_page() -> bool:
    return bool(FB_PAGE_ID and FB_PAGE_TOKEN)


def has_telegram() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


# ---------------------------------------------------------------------------
# Tham số lọc bài / lọc bình luận
# ---------------------------------------------------------------------------


@dataclass
class MineSettings:
    """Điều kiện lọc bài đáng đào và bình luận đáng đọc."""

    # Lọc bài của đối thủ
    min_comments: int = 10             # bài ít hơn ngần này bình luận thì bỏ qua
    min_reactions: int = 0
    max_age_days: int = 45             # bài cũ hơn ngần này thì bỏ (insight hết nóng)
    max_posts: int = 30                # mỗi lần đào tối đa bao nhiêu bài

    # Lọc bình luận
    min_comment_words: int = 4         # "hay quá", "❤️" — không có insight
    min_comment_score: float = 0.35    # điểm chất lượng tối thiểu (0..1)
    max_comments_per_post: int = 300

    # Gom cụm
    # Cosine tối thiểu để coi 2 bình luận là cùng ý. Bình luận Facebook rất ngắn
    # và mỗi người dùng một cách nói, nên ngưỡng phải thấp: đo thực tế thì hai câu
    # cùng hỏi học phí chỉ đạt ~0.22. Để 0.28 là hai câu đó tách thành hai cụm.
    cluster_threshold: float = 0.20
    min_cluster_size: int = 2          # cụm 1 bình luận chỉ giữ khi điểm rất cao
    max_clusters: int = 12

    @classmethod
    def from_dict(cls, d: dict | None) -> "MineSettings":
        base = cls()
        for k, v in (d or {}).items():
            if hasattr(base, k) and v is not None:
                setattr(base, k, v)
        return base


@dataclass
class WriteSettings:
    """Tham số sinh bài mới."""

    formats: tuple[str, ...] = ("post",)   # post | bullets | reels | carousel
    hooks_per_insight: int = 3
    drafts_per_insight: int = 1
    language: str = "vi"
    extra_brief: str = ""                  # ghi chú thêm cho AI (khuyến mãi, sản phẩm…)

    # Chống "xào" quá tay — xem create/originality.py
    max_similarity: float = 0.28           # trùng lặp n-gram tối đa so với bài gốc
    max_common_run: int = 12               # chuỗi từ giống hệt dài nhất được phép

    @classmethod
    def from_dict(cls, d: dict | None) -> "WriteSettings":
        base = cls()
        for k, v in (d or {}).items():
            if not hasattr(base, k) or v is None:
                continue
            setattr(base, k, tuple(v) if k == "formats" else v)
        return base


FORMAT_LABELS = {
    "post": "Bài Facebook dài",
    "bullets": "Gạch đầu dòng / Infographic",
    "reels": "Kịch bản Reels 30-45s",
    "carousel": "Carousel nhiều ảnh",
}
