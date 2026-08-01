"""Điều phối toàn bộ quy trình: phân tích -> duyệt -> render."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import (
    BrollSettings,
    CutSettings,
    RenderSettings,
    has_claude,
)
from app.jobs import Job, manager
from app.pipeline import analyze, broll, ffmpeg_utils, fillers, reframe, render, silence, subtitles, timeline
from app.pipeline.transcribe import transcribe

log = logging.getLogger(__name__)

MIN_BROLL_SCORE = 55


# ---------------------------------------------------------------------------
# Lưu / nạp dự án
# ---------------------------------------------------------------------------


def project_path(project_id: str) -> Path:
    return manager.job_dir(project_id) / "project.json"


def save_project(project_id: str, data: dict) -> None:
    project_path(project_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_project(project_id: str) -> dict | None:
    path = project_path(project_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Phân tích
# ---------------------------------------------------------------------------


def run_analysis(
    job: Job,
    video_path: Path,
    cut_settings: CutSettings,
    broll_settings: BrollSettings,
    language: str = "vi",
) -> dict:
    work = manager.job_dir(job.id)

    # --- Đọc thông tin video ---
    manager.progress(job.id, "Đọc thông tin video", 0.03)
    probe = ffmpeg_utils.probe(video_path)
    duration = probe["duration"]
    if duration <= 0:
        raise RuntimeError("Không xác định được thời lượng video.")

    ffmpeg_utils.make_thumbnail(video_path, work / "poster.jpg", at=min(1.0, duration / 2))

    # --- Tách audio ---
    manager.progress(job.id, "Tách âm thanh", 0.07)
    audio_path = ffmpeg_utils.extract_audio(video_path, work / "audio.wav")

    # --- Bóc lời ---
    manager.progress(job.id, "Bóc lời nói (Whisper)", 0.10, "Đang nạp model...")

    def _on_transcribe(frac: float, preview: str) -> None:
        manager.progress(job.id, "Bóc lời nói (Whisper)", 0.10 + 0.45 * frac, preview)

    transcript = transcribe(audio_path, language=language, on_progress=_on_transcribe)
    segments = transcript["segments"]

    # --- Dò các đoạn cần cắt ---
    cuts: list[dict] = []

    manager.progress(job.id, "Dò khoảng im lặng", 0.58)
    cuts += silence.silence_cuts(audio_path, cut_settings, duration)

    manager.progress(job.id, "Dò từ đệm", 0.62)
    cuts += fillers.filler_cuts(segments, cut_settings)

    topic = ""
    if has_claude() and (cut_settings.detect_badtakes or cut_settings.detect_offtopic):
        manager.progress(job.id, "AI đọc transcript tìm câu vấp / lạc đề", 0.66)
        result = analyze.claude_analyze(segments, cut_settings)
        topic = result.get("topic", "")
        cuts += result["badtakes"]
        cuts += result["offtopic"]
        if not result["badtakes"] and cut_settings.detect_badtakes:
            cuts += analyze.badtake_cuts_offline(segments, cut_settings)
    else:
        manager.progress(job.id, "Dò câu bị nói lại", 0.66)
        cuts += analyze.badtake_cuts_offline(segments, cut_settings)

    cuts = _dedupe_cuts(cuts, cut_settings)

    # --- B-roll ---
    brolls: list[dict] = []
    if broll_settings.enabled and broll.stock_available():
        manager.progress(job.id, "AI chọn vị trí và từ khoá B-roll", 0.72)
        slots = analyze.broll_plan(segments, broll_settings)
        if not slots:
            log.info("Không có kế hoạch B-roll (thiếu ANTHROPIC_API_KEY hoặc AI không chọn được).")
        for i, slot in enumerate(slots):
            frac = 0.75 + 0.18 * (i / max(len(slots), 1))
            manager.progress(job.id, "Tìm & tải B-roll", frac, slot["query"])
            item = _resolve_broll_slot(slot, broll_settings, work, index=i)
            if item:
                brolls.append(item)

    # --- Bám mặt để cắt dọc 9:16 ---
    manager.progress(job.id, "Bám mặt người nói (auto-reframe 9:16)", 0.94)
    interval = 0.5 if duration <= 600 else 1.0
    face_track = reframe.build_face_track(video_path, duration, sample_interval=interval)

    # --- Xem trước timeline ---
    preview = timeline.build_timeline(duration, cuts, brolls, cut_settings)

    project = {
        "project_id": job.id,
        "video_path": str(video_path),
        "video_name": video_path.name,
        "probe": probe,
        "topic": topic,
        "language": transcript["language"],
        "transcript": {"segments": segments},
        "cuts": cuts,
        "brolls": brolls,
        "face_track": face_track,
        "settings": {
            "cut": cut_settings.__dict__,
            "broll": broll_settings.__dict__,
        },
        "stats": _stats(duration, preview, cuts, brolls),
    }
    save_project(job.id, project)

    return {
        "project_id": job.id,
        "stats": project["stats"],
        "topic": topic,
        "has_claude": has_claude(),
        "has_stock": broll.stock_available(),
    }


def _dedupe_cuts(cuts: list[dict], settings: CutSettings) -> list[dict]:
    """Bỏ các đề xuất trùng nhau (ví dụ im lặng nằm trọn trong đoạn lạc đề)."""
    order = {"silence": 0, "filler": 1, "badtake": 2, "offtopic": 3}
    cuts = sorted(cuts, key=lambda c: (c["start"], order.get(c["kind"], 9)))

    kept: list[dict] = []
    for c in cuts:
        if c["end"] - c["start"] < settings.min_cut_len:
            continue
        duplicate = any(
            other["kind"] == c["kind"]
            and abs(other["start"] - c["start"]) < 0.05
            and abs(other["end"] - c["end"]) < 0.05
            for other in kept
        )
        if not duplicate:
            kept.append(c)

    for i, c in enumerate(kept):
        c["id"] = f"cut{i}"
    return kept


def _resolve_broll_slot(slot: dict, settings: BrollSettings, work: Path, index: int) -> dict | None:
    """Tìm clip stock, nhờ AI chấm điểm ngữ cảnh, tải clip thắng cuộc về."""
    candidates = broll.search_candidates(slot["query"], limit=settings.candidates_per_slot)
    if not candidates:
        return None

    ranked = analyze.rank_broll_candidates(slot.get("line", ""), slot["query"], candidates)
    idx = ranked["best_index"]
    if idx < 0:
        return None

    chosen = candidates[idx]
    local = broll.download_candidate(chosen)
    if not local:
        return None

    thumb = work / "broll_thumbs" / f"broll_{index}.jpg"
    ffmpeg_utils.make_thumbnail(local, thumb, at=0.5, width=320)

    return {
        "id": f"broll{index}",
        "segment_id": slot.get("segment_id"),
        "start": slot["start"],
        "end": slot["end"],
        "query": slot["query"],
        "query_vi": slot.get("query_vi", ""),
        "line": slot.get("line", ""),
        "reason": ranked.get("reason") or slot.get("reason", ""),
        "score": ranked.get("score", 0),
        "provider": chosen["provider"],
        "credit": chosen.get("credit", ""),
        "page": chosen.get("page", ""),
        "local_path": str(local),
        "broll_in": 0.0,
        "thumb": f"broll_thumbs/broll_{index}.jpg" if thumb.exists() else None,
        "candidates": candidates,
        "enabled": ranked.get("score", 0) >= MIN_BROLL_SCORE,
    }


def _stats(duration: float, preview: dict, cuts: list[dict], brolls: list[dict]) -> dict:
    by_kind: dict[str, int] = {}
    removed = 0.0
    for c in cuts:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
        if c.get("enabled"):
            removed += c["end"] - c["start"]
    return {
        "duration": round(duration, 2),
        "output_duration": preview["total"],
        "removed": round(duration - preview["total"], 2),
        "cut_count": len(cuts),
        "cut_by_kind": by_kind,
        "broll_count": len(brolls),
        "broll_enabled": sum(1 for b in brolls if b.get("enabled")),
    }


# ---------------------------------------------------------------------------
# 2. Render
# ---------------------------------------------------------------------------


def run_render(
    job: Job,
    project: dict,
    cuts: list[dict],
    brolls: list[dict],
    cut_settings: CutSettings,
    render_settings: RenderSettings,
) -> dict:
    work = manager.job_dir(project["project_id"])
    src = Path(project["video_path"])
    if not src.exists():
        raise RuntimeError(f"Không tìm thấy file gốc: {src}")

    probe = project["probe"]
    duration = probe["duration"]
    face_track = [tuple(x) for x in (project.get("face_track") or [])]

    manager.progress(job.id, "Dựng timeline", 0.03)
    tl = timeline.build_timeline(duration, cuts, brolls, cut_settings)
    if not tl["clips"]:
        raise RuntimeError("Không còn đoạn nào để render — hãy bỏ bớt tick cắt.")

    outputs: dict[str, str] = {}
    out_dir = work / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(project["video_name"]).stem

    # --- Phụ đề ---
    srt_path: Path | None = None
    if render_settings.export_srt or render_settings.burn_subtitles:
        manager.progress(job.id, "Tạo phụ đề", 0.06)
        srt_path = subtitles.build_srt(
            project["transcript"]["segments"], tl["keeps"], out_dir / f"{stem}.srt"
        )
        if render_settings.export_srt:
            outputs["srt"] = srt_path.name

    targets: list[tuple[str, bool]] = []
    if render_settings.vertical:
        targets.append(("vertical", True))
    if render_settings.keep_original_ratio or not render_settings.vertical:
        targets.append(("original", False))

    span = 0.9 / max(len(targets), 1)
    for i, (label, vertical) in enumerate(targets):
        base = 0.08 + i * span
        suffix = "_9x16" if vertical else "_goc"
        raw_out = out_dir / f"{stem}{suffix}.mp4"

        def _prog(frac: float, msg: str, _base=base) -> None:
            manager.progress(job.id, f"Render bản {label}", _base + span * 0.9 * frac, msg)

        render.render(
            src=src,
            probe=probe,
            timeline=tl,
            out_path=raw_out,
            settings=render_settings,
            work_dir=work,
            vertical=vertical,
            face_track=face_track,
            on_progress=_prog,
        )

        final = raw_out
        if render_settings.burn_subtitles and srt_path and srt_path.exists():
            manager.progress(job.id, f"Nướng phụ đề bản {label}", base + span * 0.95)
            burned = out_dir / f"{stem}{suffix}_sub.mp4"
            render.burn_subtitles(raw_out, srt_path, burned, render_settings, vertical)
            raw_out.unlink(missing_ok=True)
            final = burned

        outputs[label] = final.name

    project["cuts"] = cuts
    project["brolls"] = brolls
    project["last_render"] = {"outputs": outputs, "total": tl["total"]}
    save_project(project["project_id"], project)

    return {
        "project_id": project["project_id"],
        "outputs": outputs,
        "output_duration": tl["total"],
        "clip_count": len(tl["clips"]),
    }
