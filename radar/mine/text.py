"""Xử lý chữ tiếng Việt ở mức đủ dùng — không cần thư viện tách từ nặng.

Tiếng Việt viết rời từng tiếng, nên chỉ so từng tiếng thì "học phí" và "phí
học" giống hệt nhau. Vì vậy chỗ nào so sánh cũng dùng cả tiếng đơn lẫn cặp
hai tiếng liền nhau (bigram).
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")

# Từ quá phổ biến, có mặt ở mọi bình luận nên không phân biệt được gì
STOPWORDS = {
    "là", "và", "của", "có", "cho", "với", "được", "này", "đó", "thì", "mà", "ở",
    "các", "những", "một", "trong", "khi", "đã", "sẽ", "cũng", "rất", "lại", "nhé",
    "ạ", "à", "ơi", "vậy", "nha", "nhỉ", "em", "anh", "chị", "mình", "bạn", "tôi",
    "shop", "ad", "b", "e", "a", "c", "ko", "k", "hok", "dc", "đc", "j", "gì",
    "để", "về", "từ", "đi", "ra", "vào", "lên", "xuống", "nữa", "luôn", "quá",
}


def strip_accents(text: str) -> str:
    """Bỏ dấu để 'khong' và 'không' về cùng một dạng khi so khớp."""
    decomposed = unicodedata.normalize("NFD", text)
    return unicodedata.normalize(
        "NFC", "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    ).replace("đ", "d").replace("Đ", "D")


def normalize(text: str) -> str:
    return _SPACES.sub(" ", _PUNCT.sub(" ", (text or "").lower())).strip()


def words(text: str, keep_stopwords: bool = False) -> list[str]:
    tokens = normalize(text).split()
    if keep_stopwords:
        return tokens
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def features(text: str) -> list[str]:
    """Đặc trưng để gom cụm: tiếng đơn (bỏ dấu) + cặp hai tiếng liền nhau."""
    toks = [strip_accents(w) for w in words(text)]
    grams = list(toks)
    grams += [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    return grams


def shingles(text: str, n: int = 5) -> set[str]:
    """Cụm n tiếng liên tiếp — dùng để đo độ trùng lặp với bài gốc."""
    toks = [strip_accents(w) for w in normalize(text).split()]
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def longest_common_run(a: str, b: str) -> int:
    """Chuỗi tiếng giống hệt dài nhất giữa hai văn bản (đơn vị: tiếng)."""
    xs = [strip_accents(w) for w in normalize(a).split()]
    ys = [strip_accents(w) for w in normalize(b).split()]
    if not xs or not ys:
        return 0

    prev = [0] * (len(ys) + 1)
    best = 0
    for i in range(1, len(xs) + 1):
        cur = [0] * (len(ys) + 1)
        for j in range(1, len(ys) + 1):
            if xs[i - 1] == ys[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best
