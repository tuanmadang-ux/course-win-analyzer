"""Nhập từ file đã xuất sẵn: CSV, JSON, JSONL.

Dùng khi bạn đã có dữ liệu từ một công cụ khác (Apify chạy tay, Meta Content
Library, tool social listening bạn đang trả tiền…). Không cần biết công cụ đó
đặt tên cột kiểu gì — phần đoán tên cột nằm ở normalize.pick().
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from radar.ingest.normalize import pick

_COMMENT_KEYS = ("commentId", "comment_id", "commentUrl", "comment_url", "replyToId")
_PARENT_KEYS = ("postId", "post_id", "postUrl", "post_url", "facebookUrl", "parentPostUrl")
_OWN_URL_KEYS = ("url", "link", "permalink", "permalink_url")
# Chỉ bài mới có mấy trường này; bình luận thì không
_POST_STAT_KEYS = ("comments", "commentsCount", "comment_count", "shares", "sharesCount",
                   "share_count")
_NESTED_KEYS = ("comments", "topComments", "commentsList", "commentsData", "comments_list")


def load_records(path: Path) -> list[dict]:
    """Đọc file thành danh sách bản ghi thô."""
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    if suffix == ".jsonl" or (suffix == ".json" and text.lstrip().startswith("{") and "\n{" in text):
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if out:
            return out

    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("items", "data", "results", "posts"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        return data if isinstance(data, list) else []

    if suffix in (".csv", ".tsv"):
        delim = "\t" if suffix == ".tsv" else _sniff_delimiter(text)
        return list(csv.DictReader(text.splitlines(), delimiter=delim))

    raise ValueError(f"Chưa hỗ trợ định dạng {suffix or '(không rõ)'}. Dùng .json, .jsonl hoặc .csv")


def _sniff_delimiter(text: str) -> str:
    head = "\n".join(text.splitlines()[:5])
    try:
        return csv.Sniffer().sniff(head, delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def _is_comment(rec: dict) -> bool:
    """Bản ghi này là bình luận hay là bài?

    Chỗ dễ nhầm: bài của Apify cũng mang trường `postId` — đó là id của CHÍNH NÓ,
    không phải link tới bài cha. Nên chỉ khi có id bình luận rõ ràng, hoặc khi có
    khoá trỏ về bài cha mà bản thân bản ghi lại không có link riêng và không có
    chỉ số chỉ bài mới có, thì mới coi là bình luận.
    """
    if any(k in rec and rec[k] for k in _COMMENT_KEYS):
        return True
    has_parent = any(k in rec and rec[k] for k in _PARENT_KEYS)
    has_own_url = any(k in rec and rec[k] for k in _OWN_URL_KEYS)
    has_post_stats = any(k in rec and rec[k] not in (None, "") for k in _POST_STAT_KEYS)
    return has_parent and not has_own_url and not has_post_stats


def _parent_key(rec: dict) -> str:
    return str(pick(rec, *_PARENT_KEYS, default="") or "").strip()


def _post_keys(rec: dict) -> list[str]:
    keys = [
        str(pick(rec, "postId", "post_id", "id", default="") or "").strip(),
        str(pick(rec, "url", "postUrl", "link", "permalink", default="") or "").strip(),
    ]
    return [k for k in keys if k]


def split_records(records: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    """Tách thành (danh sách bài, bình luận gom theo khoá bài).

    Ba kiểu file đều nhận được:
      * bài có sẵn mảng bình luận lồng bên trong
      * file toàn bài + file toàn bình luận trộn chung
      * file chỉ có bình luận (kèm link bài cha)
    """
    posts: list[dict] = []
    comments: dict[str, list[dict]] = {}

    for rec in records:
        if not isinstance(rec, dict):
            continue

        if _is_comment(rec):
            comments.setdefault(_parent_key(rec), []).append(rec)
            continue

        nested: list[dict] = []
        for key in _NESTED_KEYS:
            value = rec.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                nested = value
                break
        posts.append(rec)
        if nested:
            for k in _post_keys(rec):
                comments.setdefault(k, []).extend(nested)

    return posts, comments


def comments_for(post_raw: dict, comments: dict[str, list[dict]]) -> list[dict]:
    """Lấy bình luận của một bài, thử lần lượt id rồi tới url."""
    seen: set[int] = set()
    out: list[dict] = []
    for key in _post_keys(post_raw):
        for c in comments.get(key, []):
            if id(c) not in seen:
                seen.add(id(c))
                out.append(c)
    return out
