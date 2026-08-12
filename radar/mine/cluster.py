"""Gom bình luận cùng ý về một cụm.

Mười người hỏi "học xong có việc làm không" theo mười cách khác nhau thì đó là
MỘT insight, không phải mười. Gom cụm để thấy được điều đó — và để biết cái
nào nhiều người hỏi nhất.

Dùng TF-IDF + cosine viết tay (dict thưa), không kéo thêm thư viện nào.
"""

from __future__ import annotations

import math
from collections import Counter

from radar.config import MineSettings
from radar.mine.text import features


def _vectors(docs: list[str]) -> list[dict[str, float]]:
    tf_list = [Counter(features(d)) for d in docs]

    df: Counter[str] = Counter()
    for tf in tf_list:
        df.update(tf.keys())

    n = len(docs)
    vectors: list[dict[str, float]] = []
    for tf in tf_list:
        vec: dict[str, float] = {}
        for term, count in tf.items():
            idf = math.log((n + 1) / (df[term] + 1)) + 1.0
            vec[term] = (1 + math.log(count)) * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({t: v / norm for t, v in vec.items()})
    return vectors


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


def _merge(centroid: dict[str, float], vec: dict[str, float], size: int) -> dict[str, float]:
    merged = {t: w * size for t, w in centroid.items()}
    for t, w in vec.items():
        merged[t] = merged.get(t, 0.0) + w
    norm = math.sqrt(sum(v * v for v in merged.values())) or 1.0
    return {t: v / norm for t, v in merged.items()}


def cluster_comments(comments: list[dict], settings: MineSettings) -> list[dict]:
    """Trả về danh sách cụm, mỗi cụm: {members, size, score, kind, top_text}."""
    if not comments:
        return []

    ordered = sorted(comments, key=lambda c: c["score"], reverse=True)
    vectors = _vectors([c.get("text", "") for c in ordered])

    centroids: list[dict[str, float]] = []
    groups: list[list[dict]] = []

    for comment, vec in zip(ordered, vectors):
        best_i, best_sim = -1, 0.0
        for i, centroid in enumerate(centroids):
            sim = cosine(centroid, vec)
            if sim > best_sim:
                best_i, best_sim = i, sim

        if best_i >= 0 and best_sim >= settings.cluster_threshold:
            centroids[best_i] = _merge(centroids[best_i], vec, len(groups[best_i]))
            groups[best_i].append(comment)
        else:
            centroids.append(vec)
            groups.append([comment])

    clusters = []
    for members in groups:
        size = len(members)
        if size < settings.min_cluster_size and members[0]["score"] < 0.75:
            continue  # cụm lẻ loi, trừ khi bình luận đó quá chất
        kinds = Counter(m["kind"] for m in members)
        total_score = sum(m["score"] for m in members)
        clusters.append({
            "members": members,
            "size": size,
            "kind": kinds.most_common(1)[0][0],
            "top_text": members[0].get("text", ""),
            # Nhiều người cùng nói > một người nói hay
            "score": round(total_score * (1 + math.log(size)), 4),
        })

    clusters.sort(key=lambda c: c["score"], reverse=True)
    return clusters[: settings.max_clusters]
