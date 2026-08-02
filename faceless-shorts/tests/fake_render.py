#!/usr/bin/env python3
"""
Giả lập đúng những gì Remotion in ra, để test khâu đọc tiến độ mà không phải
render thật (một lần render thật mất 40s+).

Các dòng dưới đây chép từ log render thật, gồm cả những chỗ từng làm sai:
  - tiến độ ghi bằng \\r (không xuống dòng) nên hay bị dính vào dòng kế tiếp;
  - "Detected differing memory amounts" chen ngang giữa dòng tiến độ;
  - "Downloading NN% of chrome" — dòng tải trình duyệt, KHÔNG phải tiến độ render.

    python3 fake_render.py <CompId> [--fail] [--hang] [--browser-noise]
"""
from __future__ import annotations

import sys
import time

argv = sys.argv[1:]
comp = argv[0] if argv and not argv[0].startswith("--") else "FakeShot"
fail = "--fail" in argv
hang = "--hang" in argv
noise = "--browser-noise" in argv

out = sys.stdout
out.write("bundling...\n")
out.flush()

if noise:
    # Remotion tự tải Chrome khi máy chưa có sẵn — dòng này có '%' nhưng
    # không phải tiến độ render.
    out.write("Downloading Chrome Headless Shell\n")
    out.write("Downloading 50% of chrome\n")
    out.flush()

if hang:
    time.sleep(300)  # để test huỷ giữa chừng
    sys.exit(0)

for pct in (0, 8, 30, 51, 72, 92):
    out.write(f"\r  {comp}: {pct}%   ")
    if pct == 0:
        # Cảnh báo bộ nhớ chen ngang, dính vào dòng tiến độ đang dở.
        out.write("Detected differing memory amounts:\n")
        out.write("Memory reported by Node: 14902.10 MB\n")
    out.flush()
    time.sleep(0.02)

if noise:
    # Dòng nhiễu ĐỨNG SAU tiến độ 92%: nếu bộ đọc bắt bừa '%' thì thanh tiến
    # độ sẽ tụt về 50%.
    out.write("\nDownloading 50% of chrome\n")
    out.flush()

if fail:
    sys.stderr.write("Error: something broke\n")
    sys.exit(1)

out.write("\n  -> out/%s.mp4\n" % comp)
out.write("done: 1 shot(s) rendered to out/\n")
out.flush()
sys.exit(0)
