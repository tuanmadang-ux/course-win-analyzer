"""Đường dẫn, cổng, và dò công cụ cho bảng điều khiển render."""

from __future__ import annotations

import glob
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMOTION_DIR = ROOT / "remotion"
OUT_DIR = REMOTION_DIR / "out"
QA_DIR = OUT_DIR / "qa"
MANIFEST = REMOTION_DIR / "src" / "shots.manifest.json"

# Thư mục dự án theo từng track — dùng để tìm beats.json/script.md của mỗi shot.
TRACK_DIRS = {
    "tsx": ROOT / "shorts",
    "ai": ROOT / "ai-shorts",
    "vox": ROOT / "vox-shorts",
}

PORT = int(os.environ.get("FACELESS_PORT", "8770"))

# Ứng viên trình duyệt, xếp theo thứ tự ưu tiên. Remotion tự tải Chrome Headless
# Shell từ remotion.media; máy nào chặn egress thì phải trỏ tay vào Chrome sẵn có.
_BROWSER_GLOBS = [
    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell",
    "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def node_available() -> bool:
    return shutil.which("node") is not None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def deps_installed() -> bool:
    return (REMOTION_DIR / "node_modules" / "remotion").exists()


def find_browser() -> str | None:
    """Trả về Chrome/Chromium dùng được, hoặc None để Remotion tự tải."""
    env = os.environ.get("REMOTION_BROWSER_EXECUTABLE")
    if env and Path(env).exists():
        return env
    for pattern in _BROWSER_GLOBS:
        for hit in sorted(glob.glob(pattern), reverse=True):
            if os.access(hit, os.X_OK):
                return hit
    return None


def render_env() -> dict[str, str]:
    """Môi trường cho tiến trình render con."""
    env = dict(os.environ)
    browser = find_browser()
    if browser:
        env["REMOTION_BROWSER_EXECUTABLE"] = browser
    return env
