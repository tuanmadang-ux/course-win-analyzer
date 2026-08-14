"""Ghép thành phẩm: chuẩn hoá từng cảnh -> nối -> trộn nhạc -> nướng phụ đề."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import FFMPEG, RenderSettings
from app.pipeline.ffmpeg_utils import FFmpegError, run
from app.pipeline.render import VENC, run_encode

log = logging.getLogger(__name__)

OUT_W, OUT_H = 1080, 1920
FPS = 25.0


def conform(
    src: Path,
    dest: Path,
    render: RenderSettings,
    audio: Path | None = None,
    duration: float | None = None,
) -> Path:
    """Ép một cảnh về đúng 1080x1920 / 25fps / AAC 48k stereo.

    Các engine nhép môi trả về đủ thứ kích thước và fps khác nhau; không ép về
    cùng một chuẩn thì bước nối bằng `concat` sẽ hỏng tiếng hoặc nhảy hình.

    `audio` — nếu truyền vào thì thay hẳn tiếng của clip bằng file này. Dùng cho
    engine local: hình do model dựng, còn tiếng vẫn là bản TTS gốc, nhờ vậy mốc
    thời gian của phụ đề khớp tuyệt đối.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if audio is not None:
        cmd += ["-i", str(audio)]

    vf = (
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop={OUT_W}:{OUT_H},fps={FPS:g},setsar=1"
    )
    cmd += ["-vf", vf, VENC]
    cmd += ["-c:a", "aac", "-b:a", render.audio_bitrate, "-ar", "48000", "-ac", "2"]
    cmd += ["-map", "0:v:0", "-map", ("1:a:0" if audio is not None else "0:a:0")]

    if duration is not None:
        cmd += ["-t", f"{max(duration, 0.05):.3f}"]
    cmd += ["-shortest", str(dest)]

    run_encode(cmd, render)
    return dest


def concat(parts: list[Path], dest: Path, work_dir: Path, render: RenderSettings) -> Path:
    """Nối các cảnh đã chuẩn hoá."""
    if not parts:
        raise FFmpegError("Không có cảnh nào để ghép.")

    if len(parts) == 1:
        dest.parent.mkdir(parents=True, exist_ok=True)
        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(parts[0]), "-c", "copy", "-movflags", "+faststart", str(dest),
        ])
        return dest

    list_file = work_dir / "concat.txt"
    list_file.parent.mkdir(parents=True, exist_ok=True)
    with open(list_file, "w", encoding="utf-8") as fh:
        for p in parts:
            escaped = str(p.resolve()).replace("'", r"'\''")
            fh.write(f"file '{escaped}'\n")

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart",
            str(dest),
        ])
    except FFmpegError:
        log.warning("Nối kiểu copy thất bại, chuyển sang nối có mã hoá lại.")
        run_encode([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            VENC,
            "-c:a", "aac", "-b:a", render.audio_bitrate, "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(dest),
        ], render)
    return dest


def _escape(path: Path) -> str:
    s = str(path.resolve()).replace("\\", "/")
    return s.replace(":", r"\:").replace("'", r"\'")


def burn_subtitles(src: Path, ass: Path, dest: Path, render: RenderSettings) -> Path:
    """Nướng phụ đề ASS lên hình. Kiểu chữ đã nằm sẵn trong file .ass."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_encode([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-vf", f"subtitles='{_escape(ass)}'",
        VENC,
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(dest),
    ], render)
    return dest


def poster(src: Path, dest: Path, at: float = 0.6) -> Path | None:
    """Ảnh bìa để hiện trong giao diện."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(at, 0):.3f}", "-i", str(src),
            "-frames:v", "1", "-vf", "scale=360:-2",
            str(dest),
        ])
        return dest
    except FFmpegError:
        return None
