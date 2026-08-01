"""Các tiện ích gọi ffmpeg/ffprobe."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.config import FFMPEG, FFPROBE


class FFmpegError(RuntimeError):
    pass


def run(cmd: list[str], timeout: int | None = None) -> str:
    """Chạy một lệnh và trả về stderr (ffmpeg ghi log ra stderr)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-2000:]
        raise FFmpegError(f"Lệnh thất bại: {' '.join(cmd[:4])} ...\n{tail}")
    return proc.stderr or ""


def run_tolerant(cmd: list[str], timeout: int | None = None) -> str:
    """Chạy lệnh nhưng không ném lỗi khi returncode != 0 (dùng cho silencedetect)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (proc.stderr or "") + (proc.stdout or "")


def probe(path: Path) -> dict:
    """Đọc metadata video: thời lượng, kích thước, fps, có audio hay không."""
    cmd = [
        FFPROBE,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"Không đọc được file video:\n{proc.stderr[-1000:]}")

    data = json.loads(proc.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise FFmpegError("File này không có luồng hình (video stream).")

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0.0)

    fps = 30.0
    raw_fps = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    try:
        num, _, den = raw_fps.partition("/")
        if den and float(den) != 0:
            fps = float(num) / float(den)
    except Exception:
        pass

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)

    # Xoay 90/270 độ thì chiều rộng/cao thực tế bị đảo
    rotation = 0
    for side in (video.get("side_data_list") or []):
        if "rotation" in side:
            try:
                rotation = int(abs(float(side["rotation"]))) % 360
            except Exception:
                pass
    if rotation in (90, 270):
        width, height = height, width

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps if fps > 0 else 30.0,
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name"),
        "audio_codec": (audio or {}).get("codec_name"),
    }


def extract_audio(src: Path, dst: Path, sample_rate: int = 16000) -> Path:
    """Tách audio thành wav mono 16k để đưa vào Whisper."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-c:a", "pcm_s16le",
        str(dst),
    ])
    return dst


def make_thumbnail(src: Path, dst: Path, at: float = 1.0, width: int = 480) -> Path | None:
    """Lấy 1 khung hình làm ảnh đại diện."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(at, 0):.3f}",
            "-i", str(src),
            "-frames:v", "1",
            "-vf", f"scale={width}:-2",
            str(dst),
        ])
        return dst
    except FFmpegError:
        return None
