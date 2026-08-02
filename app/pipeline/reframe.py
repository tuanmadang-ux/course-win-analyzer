"""Bám mặt người nói để quyết định vị trí khung cắt 9:16 (auto-reframe).

Cách làm: lấy mẫu vài khung hình mỗi giây, dò mặt bằng Haar cascade có sẵn trong
OpenCV (không cần tải model), rồi làm mượt quỹ đạo. Mỗi đoạn clip khi render sẽ
dùng một vị trí crop cố định lấy từ quỹ đạo này — ổn định, không bị rung.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CENTER = 0.5


def build_face_track(video_path: Path, duration: float, sample_interval: float = 0.5) -> list[tuple[float, float]]:
    """Trả về danh sách (thời điểm, tâm_x dạng tỉ lệ 0..1)."""
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        log.warning("Không nạp được OpenCV (%s) — dùng crop giữa khung.", exc)
        return []

    # OpenCV 5.x đã bỏ CascadeClassifier. Nếu không có, lùi về crop giữa khung
    # thay vì làm chết cả job phân tích.
    try:
        cascade_dir = getattr(getattr(cv2, "data", None), "haarcascades", "")
        cascade = cv2.CascadeClassifier(cascade_dir + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            raise RuntimeError("file cascade rỗng hoặc không tìm thấy")
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Không dùng được bộ dò mặt Haar (%s) — video dọc sẽ crop giữa khung. "
            "Muốn bật lại tính năng bám mặt: pip install 'opencv-python-headless<5'.",
            exc,
        )
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    raw: list[tuple[float, float | None]] = []
    try:
        t = 0.0
        while t < duration:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            h, w = frame.shape[:2]
            scale = 480.0 / max(w, 1)
            if scale < 1.0:
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)

            faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
            if len(faces):
                # Mặt to nhất là người nói chính
                fx, _fy, fw, _fh = max(faces, key=lambda f: f[2] * f[3])
                raw.append((t, (fx + fw / 2.0) / max(gray.shape[1], 1)))
            else:
                raw.append((t, None))
            t += sample_interval
    finally:
        cap.release()

    return _fill_and_smooth(raw)


def _fill_and_smooth(raw: list[tuple[float, float | None]], alpha: float = 0.25) -> list[tuple[float, float]]:
    """Điền chỗ không thấy mặt bằng giá trị gần nhất, rồi làm mượt bằng EMA."""
    if not raw:
        return []

    values = [v for _t, v in raw]
    known = [v for v in values if v is not None]
    if not known:
        return [(t, DEFAULT_CENTER) for t, _ in raw]

    # Điền tiến rồi điền lùi
    last = known[0]
    filled: list[float] = []
    for v in values:
        if v is not None:
            last = v
        filled.append(last)

    smoothed: list[float] = []
    ema = filled[0]
    for v in filled:
        ema = alpha * v + (1 - alpha) * ema
        smoothed.append(ema)

    return [(raw[i][0], smoothed[i]) for i in range(len(raw))]


def center_for_range(track: list[tuple[float, float]], start: float, end: float) -> float:
    """Vị trí crop trung bình cho một đoạn clip (0..1)."""
    if not track:
        return DEFAULT_CENTER
    picks = [c for t, c in track if start - 0.25 <= t <= end + 0.25]
    if not picks:
        # Lấy mẫu gần nhất
        nearest = min(track, key=lambda tc: abs(tc[0] - start))
        return nearest[1]
    picks.sort()
    return picks[len(picks) // 2]


def crop_x(center_frac: float, src_width: int, crop_width: int) -> int:
    """Đổi tỉ lệ tâm thành toạ độ x của khung cắt, có kẹp biên."""
    x = int(round(center_frac * src_width - crop_width / 2.0))
    return max(0, min(x, max(src_width - crop_width, 0)))
