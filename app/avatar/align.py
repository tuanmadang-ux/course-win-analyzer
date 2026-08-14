"""Canh giờ phụ đề cho video tự tạo.

Khác với video quay sẵn, ở đây ta BIẾT TRƯỚC từng chữ sẽ được đọc, và biết chính
xác câu đó dài bao nhiêu giây (vì Gemini TTS trả về đúng đoạn audio đó). Nên không
cần bóc lời lại bằng Whisper — chỉ cần chia thời gian trong câu theo độ dài từng
chữ. Cách này không bao giờ sai chữ, và sai lệch thời gian trong một câu 3–6 giây
là không đáng kể.

Trọng số theo số ký tự chứ không theo số từ: "nghiêng" đọc lâu hơn "và".
"""

from __future__ import annotations

import re
from pathlib import Path

# Dấu câu kéo dài nhịp đọc, tính thêm trọng số cho từ đứng trước nó
PAUSE_WEIGHT = {",": 1.6, ";": 1.8, ":": 1.6, ".": 2.2, "!": 2.2, "?": 2.2, "…": 2.6}

MIN_LINE_SECONDS = 0.7


def _weight(word: str) -> float:
    base = float(max(len(word.strip(".,;:!?…")), 1))
    for mark, extra in PAUSE_WEIGHT.items():
        if word.endswith(mark):
            base += extra
            break
    return base


def word_times(text: str, start: float, end: float) -> list[dict]:
    """Rải mốc thời gian cho từng chữ trong một câu đã biết độ dài."""
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    span = max(end - start, 0.05)
    if not words:
        return []

    weights = [_weight(w) for w in words]
    total = sum(weights) or 1.0

    out: list[dict] = []
    cursor = start
    for word, weight in zip(words, weights):
        length = span * (weight / total)
        out.append({
            "text": word,
            "start": round(cursor, 3),
            "end": round(cursor + length, 3),
        })
        cursor += length
    return out


def build_lines(segments: list[dict], max_chars: int = 28) -> list[dict]:
    """Chẻ các câu thoại thành dòng phụ đề ngắn, hợp khung dọc."""
    lines: list[dict] = []

    for seg in segments:
        words = word_times(seg["text"], float(seg["start"]), float(seg["end"]))
        if not words:
            continue

        current: list[dict] = []
        for word in words:
            candidate = " ".join(w["text"] for w in current + [word])
            if current and len(candidate) > max_chars:
                lines.append(_line(current, seg))
                current = [word]
            else:
                current.append(word)
        if current:
            lines.append(_line(current, seg))

    return _tidy(lines)


def _line(words: list[dict], seg: dict) -> dict:
    return {
        "text": " ".join(w["text"] for w in words),
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "speaker": seg.get("speaker", 1),
    }


def _tidy(lines: list[dict]) -> list[dict]:
    """Bỏ chồng lấn và kéo dài dòng quá ngắn để mắt kịp đọc."""
    lines.sort(key=lambda l: l["start"])
    out: list[dict] = []

    for line in lines:
        if out and line["start"] < out[-1]["end"]:
            line["start"] = out[-1]["end"] + 0.001
        if line["end"] - line["start"] < MIN_LINE_SECONDS:
            line["end"] = line["start"] + MIN_LINE_SECONDS
        out.append(line)

    # Dòng cuối có thể bị đẩy quá đuôi video sau khi kéo dài — không sao, ffmpeg
    # tự cắt, nhưng cắt chồng lên nhau thì phụ đề nhảy. Nên ép lại lần nữa.
    for i in range(len(out) - 1):
        out[i]["end"] = min(out[i]["end"], out[i + 1]["start"] - 0.001)
    return [l for l in out if l["end"] > l["start"]]


def _srt_time(t: float) -> str:
    ms = int(round(max(t, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(lines: list[dict], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        for i, line in enumerate(lines, 1):
            fh.write(
                f"{i}\n{_srt_time(line['start'])} --> {_srt_time(line['end'])}\n"
                f"{line['text']}\n\n"
            )
    return dest


# --- ASS: để nướng phụ đề lên video cho đẹp --------------------------------

def _ass_time(t: float) -> str:
    cs = int(round(max(t, 0.0) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(
    lines: list[dict],
    dest: Path,
    width: int = 1080,
    height: int = 1920,
    size_percent: int = 15,
    two_speakers: bool = False,
) -> Path:
    """Phụ đề dạng ASS: chữ to, viền dày, nằm ở khoảng 1/4 dưới khung."""
    font_size = max(int(height * size_percent / 100 / 4), 28)
    margin_v = int(height * 0.18)
    outline = max(int(font_size * 0.12), 3)

    # Người nói thứ hai đổi màu chữ để khán giả bắt kịp ai đang nói
    styles = [
        f"Style: A,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},0,2,60,60,{margin_v},1",
        f"Style: B,Arial,{font_size},&H0080E5FF,&H000000FF,&H00101010,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},0,2,60,60,{margin_v},1",
    ]

    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        *styles,
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ])

    rows = []
    for line in lines:
        style = "B" if (two_speakers and line.get("speaker") == 2) else "A"
        text = line["text"].replace("\n", " ").replace("{", "(").replace("}", ")")
        rows.append(
            f"Dialogue: 0,{_ass_time(line['start'])},{_ass_time(line['end'])},"
            f"{style},,0,0,0,,{text}"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return dest
