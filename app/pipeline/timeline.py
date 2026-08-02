"""Dựng timeline: từ danh sách đoạn cắt + đoạn B-roll ra danh sách clip để render."""

from __future__ import annotations

from app.config import CutSettings


def merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Gộp các khoảng chồng lấn/dính nhau."""
    if not spans:
        return []
    spans = sorted((s, e) for s, e in spans if e > s)
    if not spans:
        return []
    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(a, b) for a, b in merged]


def invert_spans(duration: float, spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Phần còn lại của video sau khi bỏ đi các khoảng `spans`."""
    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in merge_spans(spans):
        s = max(0.0, min(s, duration))
        e = max(0.0, min(e, duration))
        if s > cursor:
            keeps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration:
        keeps.append((cursor, duration))
    return keeps


def build_keeps(duration: float, cuts: list[dict], settings: CutSettings) -> list[tuple[float, float]]:
    """Danh sách đoạn được giữ lại, đã bỏ các mẩu quá ngắn."""
    spans = [(float(c["start"]), float(c["end"])) for c in cuts if c.get("enabled")]
    keeps = invert_spans(duration, spans)
    return [(s, e) for s, e in keeps if e - s >= settings.min_keep_len]


def _intersect(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float] | None:
    s = max(a[0], b[0])
    e = min(a[1], b[1])
    return (s, e) if e - s > 0.05 else None


def build_timeline(
    duration: float,
    cuts: list[dict],
    brolls: list[dict],
    settings: CutSettings,
) -> dict:
    """
    Trả về:
      {
        "keeps": [(start, end), ...],          # theo thời gian video gốc
        "clips": [ {...}, ... ],               # thứ tự render
        "total": float                         # thời lượng thành phẩm
      }

    Mỗi clip:
      source   : "main" (hình gốc) hoặc "broll" (hình chèn, tiếng vẫn từ gốc)
      main_in / main_out : lấy tiếng (và hình nếu source=main) từ video gốc
      broll_path / broll_in : chỉ có khi source="broll"
      out_start : vị trí bắt đầu trong thành phẩm
    """
    keeps = build_keeps(duration, cuts, settings)

    active_broll = [
        b for b in brolls
        if b.get("enabled") and b.get("local_path") and float(b["end"]) > float(b["start"])
    ]
    active_broll.sort(key=lambda b: float(b["start"]))

    clips: list[dict] = []
    out_cursor = 0.0

    for keep in keeps:
        # Tìm các đoạn B-roll giao với đoạn giữ lại này
        overlaps: list[tuple[tuple[float, float], dict]] = []
        for b in active_broll:
            hit = _intersect(keep, (float(b["start"]), float(b["end"])))
            if hit:
                overlaps.append((hit, b))
        overlaps.sort(key=lambda x: x[0][0])

        cursor = keep[0]
        for (bs, be), b in overlaps:
            # B-roll nằm lọt trong đoạn B-roll trước đó thì bỏ qua, nếu không sẽ
            # sinh clip có thời lượng âm và đẩy lệch mọi clip phía sau.
            if be <= cursor + 0.05:
                continue
            bs = max(bs, cursor)
            if bs > cursor:
                clips.append(_make_clip("main", cursor, bs, out_cursor))
                out_cursor += bs - cursor
                cursor = bs
            clips.append(_make_clip("broll", cursor, be, out_cursor, broll=b))
            out_cursor += be - cursor
            cursor = be
        if cursor < keep[1]:
            clips.append(_make_clip("main", cursor, keep[1], out_cursor))
            out_cursor += keep[1] - cursor

    for i, c in enumerate(clips):
        c["index"] = i

    return {"keeps": keeps, "clips": clips, "total": round(out_cursor, 3)}


def _make_clip(source: str, start: float, end: float, out_start: float, broll: dict | None = None) -> dict:
    clip = {
        "source": source,
        "main_in": round(start, 3),
        "main_out": round(end, 3),
        "duration": round(end - start, 3),
        "out_start": round(out_start, 3),
    }
    if broll:
        clip["broll_path"] = broll["local_path"]
        clip["broll_in"] = round(float(broll.get("broll_in", 0.0)), 3)
        clip["broll_label"] = broll.get("query", "")
    return clip


# ---------------------------------------------------------------------------
# Đổi mốc thời gian gốc -> mốc thời gian thành phẩm (dùng cho phụ đề)
# ---------------------------------------------------------------------------


def remap_time(keeps: list[tuple[float, float]], t: float) -> float | None:
    """Đổi 1 mốc thời gian gốc sang mốc trong thành phẩm; None nếu mốc đó bị cắt."""
    elapsed = 0.0
    for s, e in keeps:
        if t < s:
            return None
        if t <= e:
            return round(elapsed + (t - s), 3)
        elapsed += e - s
    return None


def remap_span(keeps: list[tuple[float, float]], start: float, end: float) -> tuple[float, float] | None:
    """Đổi 1 khoảng thời gian gốc sang thành phẩm (kẹp về phần còn sống sót)."""
    elapsed = 0.0
    new_start: float | None = None
    new_end: float | None = None
    for s, e in keeps:
        seg_len = e - s
        if end > s and start < e:
            a = max(start, s)
            b = min(end, e)
            if new_start is None:
                new_start = elapsed + (a - s)
            new_end = elapsed + (b - s)
        elapsed += seg_len
    if new_start is None or new_end is None or new_end - new_start < 0.05:
        return None
    return (round(new_start, 3), round(new_end, 3))
