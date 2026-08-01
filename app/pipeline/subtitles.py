"""Sinh phụ đề .srt theo mốc thời gian của thành phẩm (sau khi đã cắt)."""

from __future__ import annotations

from pathlib import Path

from app.pipeline.timeline import remap_span

MAX_CHARS = 42          # tối đa ký tự mỗi dòng phụ đề (hợp với video dọc)
MAX_DURATION = 4.0      # tối đa số giây mỗi dòng


def _fmt(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _chunk_segment(seg: dict) -> list[dict]:
    """Chẻ một câu dài thành nhiều dòng phụ đề ngắn, dựa vào timestamp từng chữ."""
    words = seg.get("words") or []
    if not words:
        return [{"start": seg["start"], "end": seg["end"], "text": (seg.get("text") or "").strip()}]

    lines: list[dict] = []
    cur: list[dict] = []
    for w in words:
        cur.append(w)
        text = " ".join(x["text"] for x in cur)
        span = cur[-1]["end"] - cur[0]["start"]
        if len(text) >= MAX_CHARS or span >= MAX_DURATION:
            lines.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": text})
            cur = []
    if cur:
        lines.append({
            "start": cur[0]["start"],
            "end": cur[-1]["end"],
            "text": " ".join(x["text"] for x in cur),
        })
    return lines


def build_srt(segments: list[dict], keeps: list[tuple[float, float]], dest: Path) -> Path:
    """Ghi file .srt cho video thành phẩm."""
    entries: list[tuple[float, float, str]] = []

    for seg in segments:
        for line in _chunk_segment(seg):
            text = (line["text"] or "").strip()
            if not text:
                continue
            mapped = remap_span(keeps, float(line["start"]), float(line["end"]))
            if mapped is None:
                continue
            entries.append((mapped[0], mapped[1], text))

    entries.sort(key=lambda e: e[0])

    # Chống chồng lấn thời gian sau khi remap
    cleaned: list[tuple[float, float, str]] = []
    for start, end, text in entries:
        if cleaned and start < cleaned[-1][1]:
            start = cleaned[-1][1] + 0.001
        if end <= start:
            end = start + 0.4
        cleaned.append((start, end, text))

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        for i, (start, end, text) in enumerate(cleaned, 1):
            fh.write(f"{i}\n{_fmt(start)} --> {_fmt(end)}\n{text}\n\n")
    return dest
