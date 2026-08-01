"""Cấu hình toàn cục: đường dẫn, khoá API, ngưỡng cắt mặc định."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- Thư mục làm việc -------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
JOB_DIR = DATA_DIR / "jobs"
BROLL_CACHE_DIR = DATA_DIR / "broll_cache"

for _d in (UPLOAD_DIR, JOB_DIR, BROLL_CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Khoá API ---------------------------------------------------------------
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
PEXELS_API_KEY = (os.getenv("PEXELS_API_KEY") or "").strip()
PIXABAY_API_KEY = (os.getenv("PIXABAY_API_KEY") or "").strip()

ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", "claude-opus-5").strip()

# --- Whisper ----------------------------------------------------------------
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3").strip()
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto").strip()
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "auto").strip()

# --- Render -----------------------------------------------------------------
USE_NVENC = os.getenv("USE_NVENC", "1").strip() not in ("0", "false", "False", "")
PORT = int(os.getenv("PORT", "8000"))

FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")


def has_claude() -> bool:
    return bool(ANTHROPIC_API_KEY)


def has_stock() -> bool:
    return bool(PEXELS_API_KEY or PIXABAY_API_KEY)


def ffmpeg_available() -> bool:
    return shutil.which(FFMPEG) is not None and shutil.which(FFPROBE) is not None


def nvenc_available() -> bool:
    """Kiểm tra ffmpeg có build kèm h264_nvenc hay không."""
    if not USE_NVENC or not ffmpeg_available():
        return False
    try:
        out = subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return "h264_nvenc" in out.stdout
    except Exception:
        return False


# --- Tham số cắt mặc định ---------------------------------------------------


@dataclass
class CutSettings:
    """Tham số điều khiển việc cắt. Frontend gửi lên để ghi đè."""

    # Im lặng
    detect_silence: bool = True
    silence_db: float = -32.0          # ngưỡng âm lượng coi là im lặng (dBFS)
    silence_min_dur: float = 0.60      # im lặng dài hơn ngần này mới xét cắt
    silence_keep_pad: float = 0.12     # chừa lại mỗi đầu bao nhiêu giây cho tự nhiên

    # Từ đệm
    detect_fillers: bool = True
    filler_pad: float = 0.04           # nới biên mỗi đầu khi cắt từ đệm
    extra_fillers: list[str] = field(default_factory=list)

    # Vấp / nói lại
    detect_badtakes: bool = True
    badtake_similarity: float = 0.82   # độ giống nhau để coi là nói lại
    badtake_window: float = 25.0       # chỉ so các câu cách nhau dưới ngần này giây

    # Lạc đề (chỉ chạy khi có ANTHROPIC_API_KEY)
    detect_offtopic: bool = False

    # Chung
    min_cut_len: float = 0.20          # đoạn cắt ngắn hơn ngần này thì bỏ qua
    min_keep_len: float = 0.30         # đoạn giữ lại ngắn hơn ngần này thì gộp/bỏ

    @classmethod
    def from_dict(cls, d: dict | None) -> "CutSettings":
        d = d or {}
        base = cls()
        for k, v in d.items():
            if hasattr(base, k) and v is not None:
                setattr(base, k, v)
        return base


@dataclass
class BrollSettings:
    enabled: bool = True
    max_clips: int = 8                 # tối đa bao nhiêu đoạn B-roll cho cả video
    min_gap: float = 12.0              # 2 đoạn B-roll phải cách nhau ít nhất ngần này
    clip_len: float = 4.0              # độ dài mỗi đoạn B-roll (giây)
    candidates_per_slot: int = 6       # số clip stock tải về để AI chấm điểm

    @classmethod
    def from_dict(cls, d: dict | None) -> "BrollSettings":
        d = d or {}
        base = cls()
        for k, v in d.items():
            if hasattr(base, k) and v is not None:
                setattr(base, k, v)
        return base


@dataclass
class RenderSettings:
    vertical: bool = True              # xuất 9:16 cho TikTok/Reels
    keep_original_ratio: bool = False  # xuất thêm bản tỉ lệ gốc
    burn_subtitles: bool = False       # nướng phụ đề lên video
    export_srt: bool = True            # xuất file .srt riêng
    target_height: int = 1920          # 1920 -> 1080x1920
    crf: int = 20
    audio_bitrate: str = "192k"

    @classmethod
    def from_dict(cls, d: dict | None) -> "RenderSettings":
        d = d or {}
        base = cls()
        for k, v in d.items():
            if hasattr(base, k) and v is not None:
                setattr(base, k, v)
        return base
