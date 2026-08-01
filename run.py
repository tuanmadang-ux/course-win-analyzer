#!/usr/bin/env python3
"""Khởi động phần mềm. Chạy: python run.py"""

from __future__ import annotations

import sys
import threading
import webbrowser

from app.config import PORT, ffmpeg_available, has_claude
from app.pipeline.broll import stock_available


def main() -> int:
    print("=" * 62)
    print("  TRỢ LÝ CẮT VIDEO — cắt im lặng / từ đệm / vấp + chèn B-roll")
    print("=" * 62)

    if not ffmpeg_available():
        print("\n  ✗ CHƯA CÀI FFMPEG — phần mềm không chạy được nếu thiếu.")
        print("    Windows : winget install Gyan.FFmpeg")
        print("    macOS   : brew install ffmpeg")
        print("    Ubuntu  : sudo apt install ffmpeg")
        return 1
    print("  ✓ ffmpeg")

    print(f"  {'✓' if has_claude() else '·'} Claude API "
          f"{'(bật hiểu ngữ cảnh + B-roll)' if has_claude() else '(chưa có key — vẫn cắt được im lặng/từ đệm/vấp)'}")
    print(f"  {'✓' if stock_available() else '·'} Kho B-roll "
          f"{'(Pexels/Pixabay)' if stock_available() else '(chưa có key — bỏ qua B-roll)'}")

    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  Mở trình duyệt tại: {url}")
    print("  Dừng bằng Ctrl+C\n")

    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
