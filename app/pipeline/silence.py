"""Dò khoảng im lặng bằng bộ lọc silencedetect của ffmpeg."""

from __future__ import annotations

import re
from pathlib import Path

from app.config import FFMPEG, CutSettings
from app.pipeline.ffmpeg_utils import run_tolerant

_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silences(audio_path: Path, settings: CutSettings, duration: float) -> list[tuple[float, float]]:
    """Trả về danh sách (start, end) của các khoảng im lặng thô."""
    log = run_tolerant([
        FFMPEG, "-hide_banner", "-nostats",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={settings.silence_db}dB:d={settings.silence_min_dur}",
        "-f", "null", "-",
    ])

    spans: list[tuple[float, float]] = []
    pending: float | None = None

    for line in log.splitlines():
        m_start = _START_RE.search(line)
        if m_start:
            pending = max(0.0, float(m_start.group(1)))
            continue
        m_end = _END_RE.search(line)
        if m_end and pending is not None:
            end = min(duration, float(m_end.group(1)))
            if end > pending:
                spans.append((pending, end))
            pending = None

    # Im lặng kéo dài tới hết video
    if pending is not None and duration > pending:
        spans.append((pending, duration))

    return spans


def silence_cuts(
    audio_path: Path,
    settings: CutSettings,
    duration: float,
) -> list[dict]:
    """Biến khoảng im lặng thành các đề xuất cắt, có chừa đệm hai đầu."""
    if not settings.detect_silence:
        return []

    proposals: list[dict] = []
    for start, end in detect_silences(audio_path, settings, duration):
        pad = settings.silence_keep_pad
        # Im lặng ở ngay đầu/cuối video thì cắt sát hơn, không cần chừa đệm phía ngoài
        cut_start = start if start <= 0.05 else start + pad
        cut_end = end if end >= duration - 0.05 else end - pad
        if cut_end - cut_start < settings.min_cut_len:
            continue
        proposals.append({
            "start": round(cut_start, 3),
            "end": round(cut_end, 3),
            "kind": "silence",
            "reason": f"Im lặng {end - start:.1f}s",
            "text": "",
            "enabled": True,
        })
    return proposals
