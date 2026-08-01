"""Render thành phẩm: cắt từng clip -> ghép -> (tuỳ chọn) nướng phụ đề."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

from app.config import FFMPEG, RenderSettings, nvenc_available
from app.pipeline import reframe
from app.pipeline.ffmpeg_utils import FFmpegError, run

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


def _even(n: int) -> int:
    n = int(round(n))
    return n if n % 2 == 0 else n + 1


def target_size(probe: dict, settings: RenderSettings, vertical: bool) -> tuple[int, int]:
    """Kích thước khung hình của thành phẩm."""
    if vertical:
        h = _even(settings.target_height)
        return _even(h * 9 / 16), h

    src_w = probe.get("width") or 1920
    src_h = probe.get("height") or 1080
    h = _even(min(settings.target_height, src_h))
    w = _even(h * src_w / max(src_h, 1))
    return w, h


def _video_encoder(settings: RenderSettings) -> list[str]:
    if nvenc_available():
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p5",
            "-rc", "vbr",
            "-cq", str(settings.crf),
            "-b:v", "0",
            "-pix_fmt", "yuv420p",
        ]
    return [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(settings.crf),
        "-pix_fmt", "yuv420p",
    ]


def _crop_filter_main(probe: dict, out_w: int, out_h: int, center_x: float) -> str:
    """Crop theo tâm mặt người nói rồi scale về khung đích."""
    src_w = probe.get("width") or out_w
    src_h = probe.get("height") or out_h
    target_ar = out_w / out_h
    src_ar = src_w / max(src_h, 1)

    if src_ar > target_ar:
        crop_h = _even(src_h)
        crop_w = _even(min(src_w, src_h * target_ar))
    else:
        crop_w = _even(src_w)
        crop_h = _even(min(src_h, src_w / target_ar))

    x = reframe.crop_x(center_x, src_w, crop_w)
    y = max(0, (src_h - crop_h) // 2)
    return f"crop={crop_w}:{crop_h}:{x}:{y},scale={out_w}:{out_h}:flags=bicubic,setsar=1"


def _fill_filter(out_w: int, out_h: int) -> str:
    """Scale-to-fill + center crop, dùng cho B-roll (không biết trước kích thước)."""
    return (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop={out_w}:{out_h},setsar=1"
    )


def _render_main_clip(
    src: Path, clip: dict, dest: Path, probe: dict, out_w: int, out_h: int,
    fps: float, settings: RenderSettings, center_x: float, has_audio: bool,
) -> None:
    dur = clip["duration"]
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{clip['main_in']:.3f}",
        "-t", f"{dur:.3f}",
        "-i", str(src),
    ]
    if not has_audio:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]

    cmd += [
        "-vf", _crop_filter_main(probe, out_w, out_h, center_x),
        "-r", f"{fps:.4f}",
        *_video_encoder(settings),
        "-c:a", "aac", "-b:a", settings.audio_bitrate, "-ar", "48000", "-ac", "2",
        "-map", "0:v:0",
        "-map", ("1:a:0" if not has_audio else "0:a:0"),
        "-shortest",
        str(dest),
    ]
    run(cmd)


def _render_broll_clip(
    src: Path, clip: dict, dest: Path, out_w: int, out_h: int,
    fps: float, settings: RenderSettings, has_audio: bool,
) -> None:
    """Hình lấy từ B-roll, tiếng vẫn lấy từ video gốc."""
    dur = clip["duration"]
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        # Input 0: B-roll (lặp lại nếu ngắn hơn đoạn cần)
        "-stream_loop", "-1",
        "-ss", f"{clip.get('broll_in', 0.0):.3f}",
        "-t", f"{dur:.3f}",
        "-i", str(clip["broll_path"]),
        # Input 1: video gốc (chỉ lấy tiếng)
        "-ss", f"{clip['main_in']:.3f}",
        "-t", f"{dur:.3f}",
        "-i", str(src),
    ]
    if not has_audio:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]

    audio_map = "2:a:0" if not has_audio else "1:a:0"
    cmd += [
        "-vf", _fill_filter(out_w, out_h),
        "-r", f"{fps:.4f}",
        *_video_encoder(settings),
        "-c:a", "aac", "-b:a", settings.audio_bitrate, "-ar", "48000", "-ac", "2",
        "-map", "0:v:0",
        "-map", audio_map,
        "-t", f"{dur:.3f}",
        str(dest),
    ]
    run(cmd)


def _concat(parts: list[Path], dest: Path, work_dir: Path) -> None:
    list_file = work_dir / "concat.txt"
    with open(list_file, "w", encoding="utf-8") as fh:
        for p in parts:
            escaped = str(p.resolve()).replace("'", r"'\''")
            fh.write(f"file '{escaped}'\n")

    try:
        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart",
            str(dest),
        ])
    except FFmpegError:
        log.warning("Ghép kiểu copy thất bại, chuyển sang ghép có mã hoá lại.")
        run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(dest),
        ])


def _escape_for_filter(path: Path) -> str:
    s = str(path.resolve())
    s = s.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return s


def burn_subtitles(src: Path, srt: Path, dest: Path, settings: RenderSettings, vertical: bool) -> Path:
    style = (
        "FontName=Arial,Fontsize=%d,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=3,Shadow=0,Alignment=2,MarginV=%d"
        % (22 if vertical else 18, 120 if vertical else 60)
    )
    run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-vf", f"subtitles='{_escape_for_filter(srt)}':force_style='{style}'",
        *_video_encoder(settings),
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(dest),
    ])
    return dest


def render(
    src: Path,
    probe: dict,
    timeline: dict,
    out_path: Path,
    settings: RenderSettings,
    work_dir: Path,
    vertical: bool,
    face_track: list[tuple[float, float]] | None = None,
    on_progress: ProgressFn | None = None,
) -> Path:
    """Render toàn bộ timeline ra một file mp4."""
    clips = timeline["clips"]
    if not clips:
        raise FFmpegError("Timeline rỗng — mọi thứ đều bị cắt. Hãy bỏ bớt tick cắt.")

    out_w, out_h = target_size(probe, settings, vertical)
    fps = min(float(probe.get("fps") or 30.0), 60.0)
    has_audio = bool(probe.get("has_audio"))

    parts_dir = work_dir / ("parts_vertical" if vertical else "parts_original")
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)

    parts: list[Path] = []
    for i, clip in enumerate(clips):
        dest = parts_dir / f"clip_{i:04d}.mp4"
        if clip["source"] == "broll":
            _render_broll_clip(src, clip, dest, out_w, out_h, fps, settings, has_audio)
        else:
            center = reframe.center_for_range(face_track or [], clip["main_in"], clip["main_out"]) \
                if vertical else 0.5
            _render_main_clip(src, clip, dest, probe, out_w, out_h, fps, settings, center, has_audio)
        parts.append(dest)

        if on_progress:
            on_progress((i + 1) / len(clips), f"Đang render đoạn {i + 1}/{len(clips)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _concat(parts, out_path, parts_dir)
    shutil.rmtree(parts_dir, ignore_errors=True)
    return out_path
