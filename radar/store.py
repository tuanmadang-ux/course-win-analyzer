"""Lưu trữ bằng SQLite — không cần cài thêm gì, file nằm ở data/radar/radar.db.

Toàn bộ hệ thống chỉ đọc/ghi qua đây. Mỗi lần gọi mở một kết nối mới vì job
chạy ở thread riêng; SQLite ở chế độ WAL chịu được kiểu này.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from radar.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    platform    TEXT NOT NULL DEFAULT 'facebook',
    ref         TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id            TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,
    external_id   TEXT NOT NULL DEFAULT '',
    url           TEXT NOT NULL DEFAULT '',
    text          TEXT NOT NULL DEFAULT '',
    posted_at     REAL,
    reactions     INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    shares        INTEGER NOT NULL DEFAULT 0,
    adapter       TEXT NOT NULL DEFAULT '',
    fetched_at    REAL NOT NULL,
    status        TEXT NOT NULL DEFAULT 'new',
    UNIQUE (source_id, external_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id          TEXT PRIMARY KEY,
    post_id     TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL,
    likes       INTEGER NOT NULL DEFAULT 0,
    replies     INTEGER NOT NULL DEFAULT 0,
    author_hash TEXT NOT NULL DEFAULT '',
    created_at  REAL,
    kind        TEXT NOT NULL DEFAULT '',
    score       REAL NOT NULL DEFAULT 0,
    UNIQUE (post_id, external_id)
);

CREATE TABLE IF NOT EXISTS insights (
    id         TEXT PRIMARY KEY,
    post_id    TEXT NOT NULL,
    source_id  TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'question',
    title      TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    gap        TEXT NOT NULL DEFAULT '',
    quotes     TEXT NOT NULL DEFAULT '[]',
    size       INTEGER NOT NULL DEFAULT 0,
    score      REAL NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'new',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    id           TEXT PRIMARY KEY,
    insight_id   TEXT NOT NULL DEFAULT '',
    post_id      TEXT NOT NULL DEFAULT '',
    format       TEXT NOT NULL DEFAULT 'post',
    angle        TEXT NOT NULL DEFAULT '',
    hook         TEXT NOT NULL DEFAULT '',
    hooks        TEXT NOT NULL DEFAULT '[]',
    body         TEXT NOT NULL DEFAULT '',
    cta          TEXT NOT NULL DEFAULT '',
    similarity   REAL NOT NULL DEFAULT 0,
    warnings     TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'draft',
    scheduled_at REAL,
    published_id TEXT NOT NULL DEFAULT '',
    published_at REAL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id        TEXT NOT NULL,
    reach           INTEGER NOT NULL DEFAULT 0,
    impressions     INTEGER NOT NULL DEFAULT 0,
    reactions       INTEGER NOT NULL DEFAULT 0,
    comments        INTEGER NOT NULL DEFAULT 0,
    shares          INTEGER NOT NULL DEFAULT 0,
    clicks          INTEGER NOT NULL DEFAULT 0,
    engagement_rate REAL NOT NULL DEFAULT 0,
    fetched_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_source   ON posts (source_id);
CREATE INDEX IF NOT EXISTS idx_comments_post  ON comments (post_id);
CREATE INDEX IF NOT EXISTS idx_insights_post  ON insights (post_id);
CREATE INDEX IF NOT EXISTS idx_drafts_status  ON drafts (status);
CREATE INDEX IF NOT EXISTS idx_metrics_draft  ON metrics (draft_id);
"""

_JSON_FIELDS = {"quotes", "warnings", "hooks"}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for f in _JSON_FIELDS:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except json.JSONDecodeError:
                d[f] = []
    return d


def _rows(rs) -> list[dict]:
    return [_row(r) for r in rs]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Nguồn theo dõi
# ---------------------------------------------------------------------------


def add_source(name: str, ref: str = "", platform: str = "facebook", note: str = "") -> dict:
    sid = new_id()
    with connect() as conn:
        conn.execute(
            "INSERT INTO sources (id, name, platform, ref, note, active, created_at)"
            " VALUES (?,?,?,?,?,1,?)",
            (sid, name.strip(), platform, ref.strip(), note.strip(), time.time()),
        )
    return get_source(sid)  # type: ignore[return-value]


def get_source(source_id: str) -> dict | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())


def list_sources() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()
        out = _rows(rows)
    counts = _post_counts()
    for s in out:
        s["post_count"] = counts.get(s["id"], 0)
    return out


def _post_counts() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute("SELECT source_id, COUNT(*) c FROM posts GROUP BY source_id").fetchall()
    return {r["source_id"]: r["c"] for r in rows}


def set_source_active(source_id: str, active: bool) -> None:
    with connect() as conn:
        conn.execute("UPDATE sources SET active=? WHERE id=?", (1 if active else 0, source_id))


def delete_source(source_id: str) -> None:
    """Xoá nguồn kèm toàn bộ bài/bình luận/insight sinh ra từ nó."""
    with connect() as conn:
        post_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM posts WHERE source_id=?", (source_id,)).fetchall()]
        for pid in post_ids:
            conn.execute("DELETE FROM comments WHERE post_id=?", (pid,))
            conn.execute("DELETE FROM insights WHERE post_id=?", (pid,))
        conn.execute("DELETE FROM posts WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))


# ---------------------------------------------------------------------------
# Bài viết
# ---------------------------------------------------------------------------


def upsert_post(post: dict) -> str:
    """Thêm bài mới, hoặc cập nhật chỉ số nếu bài đã có. Trả về post_id."""
    now = time.time()
    external_id = post.get("external_id") or ""
    source_id = post["source_id"]

    with connect() as conn:
        existing = None
        if external_id:
            existing = conn.execute(
                "SELECT id FROM posts WHERE source_id=? AND external_id=?",
                (source_id, external_id),
            ).fetchone()

        if existing:
            pid = existing["id"]
            conn.execute(
                "UPDATE posts SET text=?, url=?, reactions=?, comment_count=?, shares=?,"
                " posted_at=COALESCE(?, posted_at), fetched_at=? WHERE id=?",
                (
                    post.get("text", ""), post.get("url", ""),
                    int(post.get("reactions", 0)), int(post.get("comment_count", 0)),
                    int(post.get("shares", 0)), post.get("posted_at"), now, pid,
                ),
            )
            return pid

        pid = new_id()
        conn.execute(
            "INSERT INTO posts (id, source_id, external_id, url, text, posted_at, reactions,"
            " comment_count, shares, adapter, fetched_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,'new')",
            (
                pid, source_id, external_id or pid, post.get("url", ""), post.get("text", ""),
                post.get("posted_at"), int(post.get("reactions", 0)),
                int(post.get("comment_count", 0)), int(post.get("shares", 0)),
                post.get("adapter", ""), now,
            ),
        )
        return pid


def get_post(post_id: str) -> dict | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone())


def list_posts(source_id: str | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT p.*, s.name AS source_name FROM posts p LEFT JOIN sources s ON s.id=p.source_id"
    args: list[Any] = []
    if source_id:
        sql += " WHERE p.source_id=?"
        args.append(source_id)
    sql += " ORDER BY COALESCE(p.posted_at, p.fetched_at) DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return _rows(conn.execute(sql, args).fetchall())


def set_post_status(post_id: str, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE posts SET status=? WHERE id=?", (status, post_id))


# ---------------------------------------------------------------------------
# Bình luận
# ---------------------------------------------------------------------------


def upsert_comments(post_id: str, comments: list[dict]) -> int:
    """Ghi bình luận đã chuẩn hoá. Trả về số bình luận MỚI thêm được."""
    added = 0
    with connect() as conn:
        for c in comments:
            ext = c.get("external_id") or ""
            if ext:
                dup = conn.execute(
                    "SELECT id FROM comments WHERE post_id=? AND external_id=?", (post_id, ext)
                ).fetchone()
                if dup:
                    continue
            conn.execute(
                "INSERT INTO comments (id, post_id, external_id, text, likes, replies,"
                " author_hash, created_at, kind, score) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id(), post_id, ext or new_id(), c.get("text", ""),
                    int(c.get("likes", 0)), int(c.get("replies", 0)),
                    c.get("author_hash", ""), c.get("created_at"),
                    c.get("kind", ""), float(c.get("score", 0.0)),
                ),
            )
            added += 1
    return added


def comments_for_post(post_id: str) -> list[dict]:
    with connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM comments WHERE post_id=? ORDER BY score DESC, likes DESC", (post_id,)
        ).fetchall())


def update_comment_scores(scored: list[dict]) -> None:
    with connect() as conn:
        for c in scored:
            conn.execute(
                "UPDATE comments SET kind=?, score=? WHERE id=?",
                (c.get("kind", ""), float(c.get("score", 0.0)), c["id"]),
            )


def comment_count(post_id: str) -> int:
    with connect() as conn:
        r = conn.execute("SELECT COUNT(*) c FROM comments WHERE post_id=?", (post_id,)).fetchone()
    return int(r["c"])


# ---------------------------------------------------------------------------
# Insight
# ---------------------------------------------------------------------------


def replace_insights(post_id: str, insights: list[dict]) -> list[dict]:
    """Insight sinh lại mỗi lần đào — ghi đè cụm cũ của đúng bài đó."""
    now = time.time()
    with connect() as conn:
        conn.execute("DELETE FROM insights WHERE post_id=? AND status='new'", (post_id,))
        for ins in insights:
            conn.execute(
                "INSERT INTO insights (id, post_id, source_id, kind, title, detail, gap,"
                " quotes, size, score, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,'new',?)",
                (
                    new_id(), post_id, ins.get("source_id", ""), ins.get("kind", "question"),
                    ins.get("title", ""), ins.get("detail", ""), ins.get("gap", ""),
                    json.dumps(ins.get("quotes", []), ensure_ascii=False),
                    int(ins.get("size", 0)), float(ins.get("score", 0.0)), now,
                ),
            )
    return list_insights(post_id=post_id)


def list_insights(post_id: str | None = None, status: str | None = None,
                  limit: int = 200) -> list[dict]:
    sql = ("SELECT i.*, p.url AS post_url, p.text AS post_text, s.name AS source_name"
           " FROM insights i LEFT JOIN posts p ON p.id=i.post_id"
           " LEFT JOIN sources s ON s.id=p.source_id WHERE 1=1")
    args: list[Any] = []
    if post_id:
        sql += " AND i.post_id=?"
        args.append(post_id)
    if status:
        sql += " AND i.status=?"
        args.append(status)
    sql += " ORDER BY i.score DESC, i.size DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return _rows(conn.execute(sql, args).fetchall())


def get_insight(insight_id: str) -> dict | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM insights WHERE id=?", (insight_id,)).fetchone())


def set_insight_status(insight_id: str, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE insights SET status=? WHERE id=?", (status, insight_id))


# ---------------------------------------------------------------------------
# Bài nháp
# ---------------------------------------------------------------------------


def add_draft(draft: dict) -> dict:
    now = time.time()
    did = new_id()
    with connect() as conn:
        conn.execute(
            "INSERT INTO drafts (id, insight_id, post_id, format, angle, hook, hooks, body, cta,"
            " similarity, warnings, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                did, draft.get("insight_id", ""), draft.get("post_id", ""),
                draft.get("format", "post"), draft.get("angle", ""), draft.get("hook", ""),
                json.dumps(draft.get("hooks", []), ensure_ascii=False),
                draft.get("body", ""), draft.get("cta", ""),
                float(draft.get("similarity", 0.0)),
                json.dumps(draft.get("warnings", []), ensure_ascii=False),
                draft.get("status", "draft"), now, now,
            ),
        )
    return get_draft(did)  # type: ignore[return-value]


def update_draft(draft_id: str, **fields) -> dict | None:
    allowed = {
        "hook", "body", "cta", "angle", "format", "status", "similarity",
        "warnings", "scheduled_at", "published_id", "published_at",
    }
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k}=?")
        args.append(json.dumps(v, ensure_ascii=False) if k in _JSON_FIELDS else v)
    if not sets:
        return get_draft(draft_id)
    sets.append("updated_at=?")
    args.extend([time.time(), draft_id])
    with connect() as conn:
        conn.execute(f"UPDATE drafts SET {', '.join(sets)} WHERE id=?", args)
    return get_draft(draft_id)


def get_draft(draft_id: str) -> dict | None:
    with connect() as conn:
        return _row(conn.execute(
            "SELECT d.*, i.title AS insight_title, i.kind AS insight_kind, p.url AS post_url"
            " FROM drafts d LEFT JOIN insights i ON i.id=d.insight_id"
            " LEFT JOIN posts p ON p.id=d.post_id WHERE d.id=?", (draft_id,)
        ).fetchone())


def list_drafts(status: str | None = None, limit: int = 200) -> list[dict]:
    sql = ("SELECT d.*, i.title AS insight_title, i.kind AS insight_kind, p.url AS post_url"
           " FROM drafts d LEFT JOIN insights i ON i.id=d.insight_id"
           " LEFT JOIN posts p ON p.id=d.post_id")
    args: list[Any] = []
    if status:
        sql += " WHERE d.status=?"
        args.append(status)
    sql += " ORDER BY d.created_at DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return _rows(conn.execute(sql, args).fetchall())


def due_drafts(now: float) -> list[dict]:
    """Bài đã duyệt + đã tới giờ đăng mà chưa đăng."""
    with connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM drafts WHERE status='scheduled' AND scheduled_at IS NOT NULL"
            " AND scheduled_at<=? ORDER BY scheduled_at", (now,)
        ).fetchall())


def delete_draft(draft_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM metrics WHERE draft_id=?", (draft_id,))
        conn.execute("DELETE FROM drafts WHERE id=?", (draft_id,))


# ---------------------------------------------------------------------------
# Chỉ số
# ---------------------------------------------------------------------------


def record_metrics(draft_id: str, m: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO metrics (draft_id, reach, impressions, reactions, comments, shares,"
            " clicks, engagement_rate, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                draft_id, int(m.get("reach", 0)), int(m.get("impressions", 0)),
                int(m.get("reactions", 0)), int(m.get("comments", 0)),
                int(m.get("shares", 0)), int(m.get("clicks", 0)),
                float(m.get("engagement_rate", 0.0)), time.time(),
            ),
        )


def latest_metrics() -> dict[str, dict]:
    """Bản ghi chỉ số mới nhất của từng bài đã đăng."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT m.* FROM metrics m JOIN (SELECT draft_id, MAX(fetched_at) mx FROM metrics"
            " GROUP BY draft_id) t ON t.draft_id=m.draft_id AND t.mx=m.fetched_at"
        ).fetchall()
    return {r["draft_id"]: dict(r) for r in rows}
