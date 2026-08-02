#!/usr/bin/env python3
"""Khởi động bảng điều khiển render. Chạy: python3 run_webapp.py"""

from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from webapp.config import (  # noqa: E402
    PORT,
    deps_installed,
    ffmpeg_available,
    find_browser,
    node_available,
)


def main() -> int:
    print("=" * 62)
    print("  XƯỞNG SHORTS — bảng điều khiển render")
    print("=" * 62)

    ok = True
    if node_available():
        print("  ✓ node")
    else:
        print("\n  ✗ CHƯA CÀI NODE — cần Node 18+ để render.")
        ok = False

    if ffmpeg_available():
        print("  ✓ ffmpeg")
    else:
        print("\n  ✗ CHƯA CÀI FFMPEG — không xuất được video.")
        print("    Ubuntu  : sudo apt install ffmpeg")
        print("    macOS   : brew install ffmpeg")
        print("    Windows : winget install Gyan.FFmpeg")
        ok = False

    if deps_installed():
        print("  ✓ thư viện Remotion")
    else:
        print("\n  ✗ CHƯA CÀI THƯ VIỆN REMOTION — chạy: bash setup.sh")
        ok = False

    if not ok:
        return 1

    browser = find_browser()
    if browser:
        print(f"  ✓ trình duyệt render ({Path(browser).name})")
    else:
        print("  · trình duyệt render (chưa có — Remotion sẽ tự tải ~150MB lần render đầu)")

    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  Mở trình duyệt tại: {url}")
    print("  Dừng bằng Ctrl+C\n")

    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run("webapp.main:app", host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
