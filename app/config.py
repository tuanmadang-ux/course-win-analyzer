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
MUSIC_DIR = Path(os.getenv("MUSIC_DIR") or DATA_DIR / "music")

for _d in (UPLOAD_DIR, JOB_DIR, BROLL_CACHE_DIR, MUSIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Khoá API ---------------------------------------------------------------
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
PEXELS_API_KEY = (os.getenv("PEXELS_API_KEY") or "").strip()
PIXABAY_API_KEY = (os.getenv("PIXABAY_API_KEY") or "").strip()

ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", "claude-opus-5").strip()

# --- Google Gemini (dùng cho phần tạo video từ ảnh) -------------------------
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash").strip()
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image").strip()
GEMINI_VEO_MODEL = os.getenv("GEMINI_VEO_MODEL", "veo-3.1-generate-preview").strip()

# --- Engine nhép môi --------------------------------------------------------
# auto | latentsync | sadtalker | wav2lip | veo | still
LIPSYNC_ENGINE = os.getenv("LIPSYNC_ENGINE", "auto").strip().lower()
# Thư mục chứa repo lip-sync đã clone (xem setup_lipsync.sh)
LIPSYNC_HOME = Path(os.getenv("LIPSYNC_HOME") or ROOT / "vendor")
LIPSYNC_PYTHON = os.getenv("LIPSYNC_PYTHON", "").strip()  # để trống -> dùng python hiện tại
LIPSYNC_TIMEOUT = int(os.getenv("LIPSYNC_TIMEOUT", "1800"))

# --- Thẻ đồ hoạ B-roll (motion graphics) ------------------------------------
# auto | hyperframes | remotion | off
MOTION_ENGINE = os.getenv("MOTION_ENGINE", "auto").strip().lower()
MOTION_HOME = Path(os.getenv("MOTION_HOME") or Path(__file__).resolve().parent / "motion")
MOTION_TIMEOUT = int(os.getenv("MOTION_TIMEOUT", "900"))
NPX_BIN = os.getenv("NPX_BIN", "npx").strip()
# Remotion tự tải Chromium riêng. Máy có tường lửa/proxy chặn thì trỏ tay vào
# một bản chrome-headless-shell có sẵn.
REMOTION_BROWSER = os.getenv("REMOTION_BROWSER", "").strip()

# --- Whisper ----------------------------------------------------------------
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3").strip()
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto").strip()
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "auto").strip()

# --- Render -----------------------------------------------------------------
USE_NVENC = os.getenv("USE_NVENC", "1").strip() not in ("0", "false", "False", "")
# 8765 chứ không phải 8000: cổng 8000 quá phổ biến (Django, nhiều server dev khác
# đều mặc định ở đó), người dùng hay bị chiếm cổng mà không hiểu vì sao không vào
# được. Bị chiếm thì run.py tự nhảy sang cổng trống khác.
PORT = int(os.getenv("PORT", "8765"))

FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")


def has_claude() -> bool:
    return bool(ANTHROPIC_API_KEY)


def has_stock() -> bool:
    return bool(PEXELS_API_KEY or PIXABAY_API_KEY)


def has_gemini() -> bool:
    return bool(GEMINI_API_KEY)


def ffmpeg_available() -> bool:
    return shutil.which(FFMPEG) is not None and shutil.which(FFPROBE) is not None


_NVENC_CACHE: bool | None = None


def nvenc_available() -> bool:
    """Kiểm tra NVENC có THỰC SỰ dùng được không.

    Chỉ xem `ffmpeg -encoders` là chưa đủ: nhiều bản ffmpeg có sẵn h264_nvenc
    nhưng máy lại thiếu driver NVIDIA (libcuda), lúc đó encode sẽ chết giữa
    chừng. Nên ở đây encode thử đúng 1 khung hình rồi mới kết luận.
    """
    global _NVENC_CACHE
    if _NVENC_CACHE is not None:
        return _NVENC_CACHE

    if not USE_NVENC or not ffmpeg_available():
        _NVENC_CACHE = False
        return False

    try:
        probe = subprocess.run(
            [
                FFMPEG, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                "-c:v", "h264_nvenc", "-frames:v", "1",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        _NVENC_CACHE = probe.returncode == 0
    except Exception:
        _NVENC_CACHE = False
    return _NVENC_CACHE


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
class AvatarSettings:
    """Tham số cho phần tạo video người nói từ ảnh."""

    # Kịch bản
    rewrite_script: bool = True        # để Gemini biên tập lại nội dung cho dễ nói
    language: str = "vi"
    style: str = "than_thien"          # than_thien | chuyen_nghiep | nang_dong | tam_su
    max_seconds: float = 90.0          # độ dài mong muốn của video

    # Giọng đọc (tên voice của Gemini TTS)
    voice_a: str = "Charon"
    voice_b: str = "Kore"
    speaking_rate: str = "vua phai"    # mô tả bằng lời, đưa vào prompt TTS
    segment_gap: float = 0.18          # khoảng nghỉ giữa hai câu (giây)

    # Hình
    engine: str = "auto"               # auto | latentsync | sadtalker | wav2lip | veo | still
    background: str = "blur"           # blur | solid | gemini
    background_color: str = "#101014"

    # Phụ đề
    subtitles: bool = True
    subtitle_size: int = 15            # % chiều cao khung -> cỡ chữ
    subtitle_max_chars: int = 28       # video dọc nên để dòng ngắn

    # Thẻ đồ hoạ B-roll
    motion: bool = True
    motion_engine: str = "auto"        # auto | hyperframes | remotion | off
    motion_max_cards: int = 4

    # Nhạc nền
    music: bool = True
    music_file: str = ""               # để trống -> tự chọn theo tâm trạng
    music_gain_db: float = -22.0       # âm lượng nhạc so với giọng nói
    music_duck: bool = True            # tự hạ nhạc khi có tiếng nói

    @classmethod
    def from_dict(cls, d: dict | None) -> "AvatarSettings":
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
