#!/usr/bin/env python3
"""Khởi động phần mềm. Chạy: python run.py"""

from __future__ import annotations

import socket
import sys
import threading
import webbrowser

from app.config import PORT, ffmpeg_available, has_claude, has_gemini
from app.pipeline.broll import stock_available


def _mark(ok: bool) -> str:
    return "✓" if ok else "·"


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(preferred: int) -> tuple[int, bool]:
    """Trả (cổng dùng được, có phải đổi cổng không).

    Cổng bị chiếm là chuyện rất hay gặp và triệu chứng của nó thì khó hiểu: máy
    chủ không lên được, trình duyệt báo không vào được, mà terminal thì có khi
    chẳng nói gì. Thà tự nhảy sang cổng trống và nói rõ, còn hơn để người dùng
    ngồi đoán.
    """
    if _is_free(preferred):
        return preferred, False

    for candidate in (preferred + 1, preferred + 2, 8800, 8900, 9123):
        if _is_free(candidate):
            return candidate, True

    # Hết cách thì để hệ điều hành tự chọn một cổng trống bất kỳ
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1], True


def _lipsync_status() -> str:
    """Engine nhép môi đang dùng. Không để lỗi ở đây chặn cả lần khởi động."""
    try:
        from app.avatar import lipsync

        found = lipsync.installed_engines()
        if found:
            return f"✓ Nhép môi        {found[0]}"
        return "· Nhép môi        chưa cài — dùng ảnh tĩnh (bash setup_lipsync.sh)"
    except Exception as exc:  # noqa: BLE001
        return f"· Nhép môi        không kiểm tra được ({exc})"


def _motion_status() -> str:
    try:
        from app.motion import engine

        found = engine.installed_engines()
        if not engine.node_available():
            return "· Thẻ đồ hoạ     chưa có Node.js 22+ (bash setup_motion.sh)"
        if found:
            return f"✓ Thẻ đồ hoạ     {found[0]}"
        return "· Thẻ đồ hoạ     chưa cài (bash setup_motion.sh hyperframes)"
    except Exception as exc:  # noqa: BLE001
        return f"· Thẻ đồ hoạ     không kiểm tra được ({exc})"


def main() -> int:
    print("=" * 66)
    print("  TRỢ LÝ VIDEO")
    print("    ✂️  Cắt video   — video quay sẵn -> cắt gọn, xuất 9:16")
    print("    🎬 Tạo video   — ảnh + nội dung -> video người đó nói")
    print("=" * 66)

    if not ffmpeg_available():
        print("\n  ✗ CHƯA CÀI FFMPEG — phần mềm không chạy được nếu thiếu.")
        print("    Windows : winget install Gyan.FFmpeg")
        print("    macOS   : brew install ffmpeg")
        print("    Ubuntu  : sudo apt install ffmpeg")
        return 1

    print("\n  Cho trang 🎬 Tạo video")
    if has_gemini():
        print("  ✓ Gemini API      sẵn sàng")
    else:
        # Đây là thứ duy nhất BẮT BUỘC cho trang tạo video, nên nói rõ ngay ở đây
        # thay vì để người dùng bấm tạo rồi mới nhận lỗi.
        print("  ✗ Gemini API      CHƯA CÓ KEY — trang Tạo video sẽ không chạy")
        print("                    Lấy miễn phí: https://aistudio.google.com/apikey")
        print("                    rồi điền GEMINI_API_KEY vào file .env")
    print(f"  {_lipsync_status()}")
    print(f"  {_motion_status()}")

    print("\n  Cho trang ✂️ Cắt video")
    print(f"  {_mark(has_claude())} Claude API      "
          f"{'hiểu ngữ cảnh + chọn B-roll' if has_claude() else 'chưa có key — vẫn cắt được im lặng/từ đệm/vấp'}")
    print(f"  {_mark(stock_available())} Kho B-roll      "
          f"{'Pexels/Pixabay' if stock_available() else 'chưa có key — bỏ qua B-roll'}")

    port, switched = pick_port(PORT)
    url = f"http://127.0.0.1:{port}"

    if switched:
        print(f"\n  ! Cổng {PORT} đang bị chương trình khác chiếm — chuyển sang {port}.")
        print(f"    Muốn cố định một cổng khác: đặt PORT=... trong file .env")

    print(f"\n  Mở trình duyệt tại: {url}")
    print(f"     ✂️  Cắt video : {url}/index.html")
    print(f"     🎬 Tạo video : {url}/avatar.html")
    if not switched:
        print(f"\n  Đổi cổng: đặt PORT=8080 trong file .env")
    print("  Dừng bằng Ctrl+C\n")

    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
