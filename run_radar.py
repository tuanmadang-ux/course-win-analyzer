#!/usr/bin/env python3
"""Khởi động Radar đối thủ. Chạy: python run_radar.py"""

from __future__ import annotations

import sys
import threading
import webbrowser

from radar.config import RADAR_PORT, has_apify, has_claude, has_page


def main() -> int:
    print("=" * 66)
    print("  RADAR ĐỐI THỦ — đào insight từ bình luận, viết bài mới, đo hiệu suất")
    print("=" * 66)

    print(f"  {'✓' if has_claude() else '·'} Claude API "
          f"{'(đào insight + viết bài)' if has_claude() else '(chưa có key — chỉ ra được dàn ý)'}")
    print(f"  {'✓' if has_apify() else '·'} Apify "
          f"{'(quét tự động)' if has_apify() else '(chưa cấu hình — dán tay hoặc nhập file CSV/JSON)'}")
    print(f"  {'✓' if has_page() else '·'} Fanpage của bạn "
          f"{'(đăng + đọc chỉ số)' if has_page() else '(chưa nối — duyệt xong copy đăng tay)'}")

    print("\n  Lưu ý: phần mềm KHÔNG tự đăng nhập Facebook và KHÔNG đăng gì khi bạn")
    print("  chưa bấm duyệt. Tên người bình luận bị ẩn danh ngay khi lưu.")

    url = f"http://127.0.0.1:{RADAR_PORT}"
    print(f"\n  Mở trình duyệt tại: {url}")
    print("  Dừng bằng Ctrl+C\n")

    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run("radar.main:app", host="127.0.0.1", port=RADAR_PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
