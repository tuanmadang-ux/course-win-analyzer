"""Dò từ đệm tiếng Việt (ừ, à, ờ, kiểu như...) dựa trên timestamp từng chữ."""

from __future__ import annotations

import re
import unicodedata

from app.config import CutSettings

# Từ đệm 1 tiếng — cắt gần như luôn an toàn.
SINGLE_FILLERS: set[str] = {
    "ừ", "ừm", "ưm", "ờ", "ờm", "à", "ạ", "ơ",
    "hmm", "hm", "um", "uhm", "uh", "eh", "er", "mmm",
}

# Cụm từ đệm — kiểm tra theo thứ tự dài trước, ngắn sau.
PHRASE_FILLERS: list[tuple[str, ...]] = [
    ("các", "bạn", "biết", "đấy"),
    ("nói", "chung", "là"),
    ("kiểu", "như", "là"),
    ("à", "thì", "là"),
    ("ừ", "thì", "là"),
    ("cái", "mà", "là"),
    ("kiểu", "như"),
    ("à", "thì"),
    ("ừ", "thì"),
    ("ờ", "thì"),
    ("thì", "là"),
]

_PUNCT_RE = re.compile(r"[^\w\sÀ-ỹ]", flags=re.UNICODE)


def normalize(token: str) -> str:
    """Bỏ dấu câu, viết thường, chuẩn hoá Unicode để so khớp ổn định."""
    token = unicodedata.normalize("NFC", token or "")
    token = _PUNCT_RE.sub("", token)
    return token.strip().lower()


def _build_phrase_list(extra: list[str]) -> tuple[list[tuple[str, ...]], set[str]]:
    phrases = list(PHRASE_FILLERS)
    singles = set(SINGLE_FILLERS)
    for raw in extra or []:
        parts = tuple(p for p in (normalize(x) for x in str(raw).split()) if p)
        if not parts:
            continue
        if len(parts) == 1:
            singles.add(parts[0])
        else:
            phrases.append(parts)
    phrases.sort(key=len, reverse=True)
    return phrases, singles


def filler_cuts(segments: list[dict], settings: CutSettings) -> list[dict]:
    """Sinh đề xuất cắt cho từng từ/cụm từ đệm tìm được."""
    if not settings.detect_fillers:
        return []

    phrases, singles = _build_phrase_list(settings.extra_fillers)
    proposals: list[dict] = []

    for seg in segments:
        words = seg.get("words") or []
        if not words:
            continue
        norms = [normalize(w["text"]) for w in words]
        i = 0
        while i < len(words):
            matched_len = 0
            matched_label = ""

            for phrase in phrases:
                n = len(phrase)
                if i + n <= len(words) and tuple(norms[i:i + n]) == phrase:
                    matched_len = n
                    matched_label = " ".join(phrase)
                    break

            if matched_len == 0 and norms[i] in singles:
                matched_len = 1
                matched_label = norms[i]

            if matched_len:
                start = words[i]["start"] - settings.filler_pad
                end = words[i + matched_len - 1]["end"] + settings.filler_pad
                start = max(0.0, start)
                if end - start >= settings.min_cut_len:
                    proposals.append({
                        "start": round(start, 3),
                        "end": round(end, 3),
                        "kind": "filler",
                        "reason": f"Từ đệm: “{matched_label}”",
                        "text": matched_label,
                        "enabled": True,
                    })
                i += matched_len
            else:
                i += 1

    return _merge_adjacent(proposals, gap=0.08)


def _merge_adjacent(props: list[dict], gap: float) -> list[dict]:
    """Gộp các đoạn cắt sát nhau để tránh cắt vụn."""
    if not props:
        return []
    props = sorted(props, key=lambda p: p["start"])
    merged = [dict(props[0])]
    for p in props[1:]:
        last = merged[-1]
        if p["start"] - last["end"] <= gap:
            last["end"] = max(last["end"], p["end"])
            if p["text"] and p["text"] not in last["text"]:
                last["text"] = f"{last['text']} {p['text']}".strip()
                last["reason"] = f"Từ đệm: “{last['text']}”"
        else:
            merged.append(dict(p))
    return merged
