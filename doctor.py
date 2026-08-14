#!/usr/bin/env python3
"""Kiểm tra vì sao phần mềm không chạy được. Chạy: python doctor.py

CHỈ dùng thư viện chuẩn của Python — không import gì của dự án, không cần cài
gì trước. Nhờ vậy nó vẫn chạy được đúng lúc mọi thứ khác đang hỏng, vốn là lúc
cần nó nhất.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

OK, BAD, MEH = "  ✓", "  ✗", "  ·"
problems: list[str] = []


def fail(line: str, fix: str) -> None:
    print(f"{BAD} {line}")
    print(f"      → {fix}")
    problems.append(line)


def main() -> int:
    print("=" * 66)
    print("  KIỂM TRA CÀI ĐẶT")
    print("=" * 66)

    # --- 1. Python ---------------------------------------------------------
    v = sys.version_info
    print(f"\n1. Python {v.major}.{v.minor}.{v.micro}")
    print(f"      {sys.executable}")
    if v < (3, 10):
        fail(f"Python {v.major}.{v.minor} quá cũ", "Cần Python 3.10 trở lên: https://python.org")
    else:
        print(f"{OK} phiên bản dùng được")

    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        print(f"{OK} đang chạy trong môi trường ảo")
    else:
        venv_py = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if venv_py.exists():
            fail(
                "CHƯA bật môi trường ảo (.venv) — đây là lỗi hay gặp nhất",
                f"Windows: .venv\\Scripts\\activate\n"
                f"      macOS/Linux: source .venv/bin/activate\n"
                f"      rồi chạy lại: python doctor.py",
            )
        else:
            fail("Chưa có môi trường ảo .venv", "Chạy: bash setup.sh   (Windows: xem README)")

    # --- 2. Đúng thư mục chưa ---------------------------------------------
    print("\n2. Thư mục dự án")
    print(f"      {ROOT}")
    if (ROOT / "app" / "main.py").exists():
        print(f"{OK} tìm thấy mã nguồn")
    else:
        fail("Không thấy app/main.py", "Chạy doctor.py từ trong thư mục đã giải nén")
        return report()

    has_avatar = (ROOT / "app" / "avatar").is_dir()
    if has_avatar:
        print(f"{OK} có phần Tạo video (app/avatar)")
    else:
        fail(
            "Bản này CHƯA có phần Tạo video",
            "Bạn đang dùng nhánh cũ. Tải lại ZIP của nhánh "
            "claude/ai-video-generation-app-w5ig5f",
        )

    # --- 3. Thư viện Python ------------------------------------------------
    print("\n3. Thư viện Python")
    missing = []
    for mod, why in (
        ("fastapi", "máy chủ web"),
        ("uvicorn", "máy chủ web"),
        ("httpx", "gọi Gemini"),
        ("dotenv", "đọc file .env"),
        ("cv2", "dò khuôn mặt"),
        ("numpy", "xử lý ảnh"),
        ("multipart", "nhận file tải lên"),
    ):
        try:
            __import__(mod)
            print(f"{OK} {mod}")
        except ImportError:
            print(f"{BAD} {mod}  ({why})")
            missing.append(mod)
    if missing:
        fail(
            f"Thiếu {len(missing)} thư viện",
            "pip install -r requirements.txt   (nhớ bật .venv trước)",
        )

    # --- 4. ffmpeg ---------------------------------------------------------
    print("\n4. ffmpeg")
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        print(f"{OK} ffmpeg và ffprobe đều có")
    else:
        fail(
            "Thiếu ffmpeg — không xuất được video",
            "Windows: winget install Gyan.FFmpeg   rồi MỞ TERMINAL MỚI\n"
            "      macOS: brew install ffmpeg\n"
            "      Ubuntu: sudo apt install ffmpeg",
        )

    # --- 5. File .env ------------------------------------------------------
    print("\n5. Cấu hình (.env)")
    # Gán trước khi rẽ nhánh: thiếu .env là đúng lúc công cụ này cần chạy được
    # nhất, mà nếu để `port` chỉ tồn tại trong nhánh có .env thì phần kiểm tra
    # cổng bên dưới sẽ chết vì biến chưa gán.
    key = ""
    port = ""
    env = ROOT / ".env"
    if not env.exists():
        fail("Chưa có file .env", "Copy .env.example thành .env rồi điền key")
    else:
        print(f"{OK} có file .env")
        text = env.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip()
            elif line.startswith("PORT="):
                port = line.split("=", 1)[1].strip()
        if key:
            print(f"{OK} GEMINI_API_KEY đã điền ({len(key)} ký tự)")
        else:
            fail(
                "GEMINI_API_KEY còn trống — trang Tạo video sẽ không chạy",
                "Lấy miễn phí ở https://aistudio.google.com/apikey rồi điền vào .env",
            )
        print(f"{MEH} PORT trong .env: {port or '(không đặt, mặc định 8419)'}")

    # --- 6. Cổng mạng ------------------------------------------------------
    print("\n6. Cổng mạng")
    wanted = int(port) if port.isdigit() else 8419
    free = None
    for candidate in (wanted, wanted + 1, wanted + 2, 8800, 8900, 9123, 9247):
        if _free(candidate):
            free = candidate
            break
        print(f"{MEH} {candidate} đang bị chương trình khác chiếm")
    if free is None:
        fail("Không tìm được cổng trống nào", "Tắt bớt phần mềm đang chạy rồi thử lại")
    else:
        print(f"{OK} cổng {free} đang trống")

    return report(free)


def _free(port: int) -> bool:
    """Có ai đang lắng nghe ở cổng này không. Không đặt SO_REUSEADDR —
    trên Windows cờ đó khiến cổng đã có chủ vẫn bị báo là trống."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def report(free: int | None = None) -> int:
    print("\n" + "=" * 66)
    if problems:
        print(f"  CÓ {len(problems)} VẤN ĐỀ CẦN SỬA:")
        for p in problems:
            print(f"    ✗ {p}")
        print("\n  Sửa theo hướng dẫn ở trên rồi chạy lại: python doctor.py")
        print("=" * 66)
        return 1

    print("  MỌI THỨ ĐỀU ỔN")
    print(f"\n  Chạy:  python run.py")
    if free:
        print(f"  Rồi mở: http://127.0.0.1:{free}/avatar.html")
        print("\n  Nhưng cứ dùng đúng địa chỉ mà run.py in ra — nó là số cuối cùng.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
