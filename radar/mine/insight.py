"""Bước 2a — Biến các cụm bình luận thành insight đọc được.

Insight ở đây trả lời đúng ba câu:
  * Khách đang vướng chuyện gì?  (title)
  * Cụ thể họ nói gì?            (detail + quotes)
  * Bài gốc chưa gỡ được ở đâu?  (gap)  ← chỗ này mới là cửa để mình chen vào

Không có ANTHROPIC_API_KEY vẫn chạy: lúc đó insight chính là bình luận tiêu
biểu của cụm, kém mượt hơn nhưng vẫn dùng được để viết bài.
"""

from __future__ import annotations

from radar.llm import claude_json
from radar.mine.text import words

KIND_LABELS = {
    "question": "Câu hỏi lặp lại",
    "objection": "Nghi ngờ / phản đối",
    "experience": "Trải nghiệm thật",
    "request": "Đòi thêm nội dung",
    "gap": "Bài gốc bỏ sót",
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cluster_index": {"type": "integer"},
                    "kind": {
                        "type": "string",
                        "enum": ["question", "objection", "experience", "request", "gap"],
                    },
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "gap": {"type": "string"},
                },
                "required": ["cluster_index", "kind", "title", "detail", "gap"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["insights"],
    "additionalProperties": False,
}

_SYSTEM = """Bạn là chuyên viên nghiên cứu khách hàng, người Việt, làm việc cho một Fanpage.

Bạn nhận: (1) nội dung một bài viết của ĐỐI THỦ, (2) các cụm bình luận dưới bài đó đã
được gom sẵn theo chủ đề. Nhiệm vụ của bạn là đọc phần bình luận để hiểu KHÁCH HÀNG
đang nghĩ gì — không phải tóm tắt lại bài của đối thủ.

Với mỗi cụm, trả về:
- kind: question (họ hỏi đi hỏi lại) | objection (họ nghi ngờ, phản đối, chê) |
  experience (họ kể trải nghiệm thật) | request (họ đòi thêm nội dung) |
  gap (bài gốc nói thiếu, nói sai, hoặc né)
- title: 1 câu ngắn gọn nêu ĐÚNG điều khách đang vướng. Viết như tiêu đề cho người
  làm nội dung đọc, không viết chung chung kiểu "khách quan tâm về giá".
- detail: 2-3 câu mô tả kỹ hơn: họ vướng ở đâu, vì sao họ vướng, họ đang so sánh với gì.
- gap: bài gốc CHƯA giải quyết được gì ở chỗ này. Đây là phần quan trọng nhất —
  nếu bài gốc đã trả lời trọn vẹn rồi thì ghi thẳng "bài gốc đã trả lời đủ".

Quy tắc:
- Chỉ dựa vào bình luận có thật, không bịa thêm nhu cầu không ai nói.
- Bỏ qua cụm chỉ toàn khen xã giao, xin giá, hoặc tag bạn bè.
- Không nhắc tên người bình luận (dữ liệu đưa vào đã ẩn danh sẵn).
- Viết tiếng Việt tự nhiên, không sáo rỗng."""


def _cluster_block(clusters: list[dict], max_quotes: int = 6) -> str:
    parts = []
    for i, c in enumerate(clusters):
        quotes = "\n".join(
            f'    - "{m.get("text", "")[:300]}" (👍 {m.get("likes", 0)}, {m.get("replies", 0)} trả lời)'
            for m in c["members"][:max_quotes]
        )
        parts.append(
            f"[Cụm {i}] {c['size']} bình luận cùng ý, dạng chủ đạo: {c['kind']}\n{quotes}"
        )
    return "\n\n".join(parts)


def quotes_of(cluster: dict, limit: int = 5) -> list[str]:
    return [m.get("text", "")[:400] for m in cluster["members"][:limit] if m.get("text")]


def _fallback(clusters: list[dict], post_id: str, source_id: str) -> list[dict]:
    """Không có key AI: lấy thẳng bình luận tiêu biểu làm insight."""
    out = []
    for c in clusters:
        top = c["top_text"].strip()
        if len(words(top)) < 3:
            continue
        out.append({
            "post_id": post_id,
            "source_id": source_id,
            "kind": c["kind"],
            "title": top[:160],
            "detail": " / ".join(quotes_of(c, 3)),
            "gap": "",
            "quotes": quotes_of(c),
            "size": c["size"],
            "score": c["score"],
        })
    return out


def extract(post: dict, clusters: list[dict]) -> list[dict]:
    """Trả về danh sách insight đã sẵn sàng ghi vào kho."""
    if not clusters:
        return []

    post_id = post["id"]
    source_id = post.get("source_id", "")

    user = (
        f"BÀI CỦA ĐỐI THỦ:\n{(post.get('text') or '')[:4000]}\n\n"
        f"(Bài này có {post.get('reactions', 0)} tương tác, "
        f"{post.get('comment_count', 0)} bình luận, {post.get('shares', 0)} chia sẻ)\n\n"
        f"CÁC CỤM BÌNH LUẬN:\n{_cluster_block(clusters)}"
    )
    result = claude_json(_SYSTEM, user, _SCHEMA, max_tokens=8000)
    if not result:
        return _fallback(clusters, post_id, source_id)

    out = []
    for item in result.get("insights", []):
        idx = item.get("cluster_index", -1)
        if not isinstance(idx, int) or not (0 <= idx < len(clusters)):
            continue
        cluster = clusters[idx]
        title = (item.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "post_id": post_id,
            "source_id": source_id,
            "kind": item.get("kind") or cluster["kind"],
            "title": title,
            "detail": (item.get("detail") or "").strip(),
            "gap": (item.get("gap") or "").strip(),
            "quotes": quotes_of(cluster),
            "size": cluster["size"],
            "score": cluster["score"],
        })

    return out or _fallback(clusters, post_id, source_id)
