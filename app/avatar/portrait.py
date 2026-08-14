"""Biến ảnh người dùng tải lên thành khung hình dọc 1080x1920 để nhép môi.

Việc cần làm khá cụ thể: ảnh chụp thường là ngang hoặc vuông, mặt nằm lung tung.
Model nhép môi lại muốn mặt to, rõ, nằm giữa khung. Còn video TikTok thì muốn mặt
nằm ở khoảng 1/3 trên để chừa chỗ dưới cho phụ đề.

Nên ở đây: dò mặt -> crop quanh mặt theo tỉ lệ 9:16 -> nếu ảnh không đủ rộng thì
lấp phần thiếu bằng chính ảnh đó phóng to + làm mờ (nhìn tự nhiên hơn viền đen).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import AvatarSettings

log = logging.getLogger(__name__)

OUT_W, OUT_H = 1080, 1920

# Mặt nên chiếm khoảng ngần này chiều cao khung, và tâm mặt nằm ở đâu theo chiều dọc.
FACE_HEIGHT_RATIO = 0.26
FACE_CENTER_Y = 0.34


class PortraitError(RuntimeError):
    pass


def _load_cv2():
    try:
        import cv2  # noqa: PLC0415

        return cv2
    except Exception as exc:  # noqa: BLE001
        raise PortraitError(
            "Không nạp được OpenCV. Chạy: pip install 'opencv-python-headless<5'"
        ) from exc


def detect_face(image_path: Path) -> tuple[int, int, int, int] | None:
    """Trả (x, y, w, h) của khuôn mặt to nhất, hoặc None nếu không thấy."""
    cv2 = _load_cv2()
    img = cv2.imread(str(image_path))
    if img is None:
        raise PortraitError(f"Không đọc được ảnh: {image_path.name}")

    try:
        cascade_dir = getattr(getattr(cv2, "data", None), "haarcascades", "")
        cascade = cv2.CascadeClassifier(cascade_dir + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            raise RuntimeError("file cascade rỗng")
    except Exception as exc:  # noqa: BLE001
        log.warning("Không dùng được bộ dò mặt (%s) — canh khung theo giữa ảnh.", exc)
        return None

    gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60))
    if len(faces) == 0:
        return None

    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    return int(x), int(y), int(w), int(h)


def build_frame(
    image_path: Path,
    dest: Path,
    settings: AvatarSettings,
    face: tuple[int, int, int, int] | None = None,
) -> dict:
    """Dựng khung 1080x1920 và trả về vị trí mặt trong khung mới."""
    cv2 = _load_cv2()
    import numpy as np  # noqa: PLC0415

    img = cv2.imread(str(image_path))
    if img is None:
        raise PortraitError(f"Không đọc được ảnh: {image_path.name}")

    src_h, src_w = img.shape[:2]
    if face is None:
        face = detect_face(image_path)

    if face is not None:
        fx, fy, fw, fh = face
        # Phóng ảnh sao cho mặt cao đúng tỉ lệ mong muốn trong khung đích
        scale = (OUT_H * FACE_HEIGHT_RATIO) / max(fh, 1)
    else:
        # Không thấy mặt: coi như ảnh chân dung chuẩn, lấp đầy chiều rộng
        fx, fy, fw, fh = src_w // 3, src_h // 4, src_w // 3, src_h // 3
        scale = OUT_W / max(src_w, 1)

    # Đừng phóng quá tay làm vỡ hình, cũng đừng thu nhỏ tới mức lọt thỏm
    scale = max(min(scale, 4.0), OUT_W / max(src_w * 3.0, 1))

    new_w, new_h = max(int(round(src_w * scale)), 2), max(int(round(src_h * scale)), 2)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    # Tâm mặt sau khi phóng, rồi tính điểm cắt để đưa nó về đúng chỗ trong khung
    face_cx = (fx + fw / 2.0) * scale
    face_cy = (fy + fh / 2.0) * scale
    off_x = int(round(face_cx - OUT_W / 2.0))
    off_y = int(round(face_cy - OUT_H * FACE_CENTER_Y))

    canvas = _background(cv2, np, resized, settings)

    # Vùng giao nhau giữa ảnh đã phóng và khung đích
    sx0, sy0 = max(off_x, 0), max(off_y, 0)
    sx1, sy1 = min(off_x + OUT_W, new_w), min(off_y + OUT_H, new_h)
    if sx1 <= sx0 or sy1 <= sy0:
        raise PortraitError("Ảnh nằm ngoài khung sau khi canh mặt — thử ảnh khác.")

    dx0, dy0 = sx0 - off_x, sy0 - off_y
    canvas[dy0:dy0 + (sy1 - sy0), dx0:dx0 + (sx1 - sx0)] = resized[sy0:sy1, sx0:sx1]

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(dest), canvas):
        raise PortraitError(f"Ghi ảnh thất bại: {dest}")

    return {
        "path": str(dest),
        "width": OUT_W,
        "height": OUT_H,
        "face_found": face is not None,
        "face_box": [
            int(round(face_cx - off_x - (fw * scale) / 2)),
            int(round(face_cy - off_y - (fh * scale) / 2)),
            int(round(fw * scale)),
            int(round(fh * scale)),
        ],
    }


def _background(cv2, np, resized, settings: AvatarSettings):
    """Nền lấp chỗ trống: ảnh phóng to làm mờ, hoặc màu đặc."""
    if settings.background == "solid":
        b, g, r = _hex_to_bgr(settings.background_color)
        canvas = np.zeros((OUT_H, OUT_W, 3), dtype=np.uint8)
        canvas[:] = (b, g, r)
        return canvas

    # Phủ đầy khung bằng chính ảnh gốc rồi làm mờ mạnh
    h, w = resized.shape[:2]
    scale = max(OUT_W / max(w, 1), OUT_H / max(h, 1))
    bw, bh = max(int(round(w * scale)), OUT_W), max(int(round(h * scale)), OUT_H)
    filled = cv2.resize(resized, (bw, bh), interpolation=cv2.INTER_LINEAR)

    x0 = max((bw - OUT_W) // 2, 0)
    y0 = max((bh - OUT_H) // 2, 0)
    cropped = filled[y0:y0 + OUT_H, x0:x0 + OUT_W]

    blurred = cv2.GaussianBlur(cropped, (0, 0), sigmaX=32, sigmaY=32)
    return cv2.convertScaleAbs(blurred, alpha=0.72, beta=0)


def _hex_to_bgr(value: str) -> tuple[int, int, int]:
    raw = (value or "").lstrip("#")
    if len(raw) != 6:
        return (20, 16, 16)
    try:
        r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (20, 16, 16)
    return (b, g, r)


def crop_face_square(image_path: Path, dest: Path, margin: float = 0.8) -> Path | None:
    """Cắt ô vuông quanh mặt — vài model nhép môi chạy tốt hơn hẳn với đầu vào này."""
    cv2 = _load_cv2()
    face = detect_face(image_path)
    if face is None:
        return None

    img = cv2.imread(str(image_path))
    if img is None:
        return None

    h, w = img.shape[:2]
    fx, fy, fw, fh = face
    side = int(round(max(fw, fh) * (1 + margin)))
    cx, cy = fx + fw // 2, fy + fh // 2

    x0 = max(cx - side // 2, 0)
    y0 = max(cy - side // 2, 0)
    x1 = min(x0 + side, w)
    y1 = min(y0 + side, h)

    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest if cv2.imwrite(str(dest), img[y0:y1, x0:x1]) else None
