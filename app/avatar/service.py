"""Điều phối toàn bộ quy trình tạo video người nói.

Ảnh + nội dung  ->  kịch bản  ->  giọng đọc  ->  khung 9:16  ->  nhép môi
                ->  phụ đề  ->  nhạc nền  ->  file mp4 dọc.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from app.avatar import align, compose, gemini, lipsync, music, portrait, script, voice
from app.config import AvatarSettings, RenderSettings
from app.jobs import Job, manager
from app.motion import service as motion_service
from app.pipeline.ffmpeg_utils import probe

log = logging.getLogger(__name__)

# Trọng số các bước để thanh tiến độ chạy đều tay
STAGES = {
    "script": (0.02, 0.08),
    "voice": (0.08, 0.30),
    "portrait": (0.30, 0.36),
    "lipsync": (0.36, 0.74),
    "motion": (0.74, 0.90),
    "compose": (0.90, 1.00),
}


def _gemini_json(prompt: str, system: str) -> dict:
    """Cầu nối để `app.motion` hỏi Gemini mà không cần biết tới module gemini."""
    return gemini.generate_json(prompt, system=system, temperature=0.4)


def _span(stage: str, fraction: float) -> float:
    lo, hi = STAGES[stage]
    return lo + (hi - lo) * max(0.0, min(fraction, 1.0))


def load_project(project_id: str) -> dict | None:
    try:
        path = manager.job_dir(project_id) / "project.json"
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def save_project(project_id: str, data: dict) -> None:
    path = manager.job_dir(project_id) / "project.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Quy trình chính
# ---------------------------------------------------------------------------


def generate(
    job: Job,
    photos: list[Path],
    content: str,
    settings: AvatarSettings,
    render: RenderSettings,
) -> dict:
    if not photos:
        raise ValueError("Chưa có ảnh nào. Hãy tải lên ít nhất 1 ảnh chân dung.")

    work = manager.job_dir(job.id)
    speakers = min(len(photos), 2)

    engine = lipsync.resolve_engine(settings.engine)
    log.info("Dự án %s: %d người nói, engine %s", job.id, speakers, engine)

    # --- 1. Kịch bản -------------------------------------------------------
    manager.progress(job.id, "Viết kịch bản", _span("script", 0.2), "Đang chia câu thoại…")
    plan = script.plan(content, settings, speakers)
    if not plan["segments"]:
        raise ValueError("Không tách được câu thoại nào từ nội dung bạn nhập.")

    manager.progress(
        job.id, "Viết kịch bản", _span("script", 1.0),
        f"{len(plan['segments'])} câu thoại",
    )

    # --- 2. Khung hình chân dung ------------------------------------------
    # Làm trước phần tiếng vì lỗi ảnh (không dò được mặt) nên báo sớm, đừng để
    # người dùng chờ hết phần TTS tốn tiền rồi mới biết ảnh không dùng được.
    manager.progress(job.id, "Dựng khung hình", _span("portrait", 0.1), "Đang canh khuôn mặt…")
    frames: dict[int, dict] = {}
    for i, photo in enumerate(photos[:2], start=1):
        frames[i] = portrait.build_frame(photo, work / "portraits" / f"speaker_{i}.png", settings)
        if not frames[i]["face_found"]:
            log.warning("Ảnh người %d không dò được mặt — canh theo giữa ảnh.", i)

    # --- 3. Tiếng + hình ---------------------------------------------------
    if engine == "veo":
        timeline = _run_veo(job, plan, frames, settings, render, work)
    else:
        timeline = _run_local(job, plan, frames, settings, render, work, engine)

    segments = timeline["segments"]
    clips = timeline["clips"]
    duration = timeline["duration"]

    # --- 4. Ghép -----------------------------------------------------------
    manager.progress(job.id, "Ghép video", _span("compose", 0.1), "Đang nối các cảnh…")
    out_dir = work / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    stitched = compose.concat(clips, work / "stitched.mp4", work, render)

    # Độ dài thật sau khi nối mới là mốc chuẩn để cắt nhạc
    try:
        duration = float(probe(stitched).get("duration") or duration)
    except Exception:  # noqa: BLE001
        pass

    # --- 5. Thẻ đồ hoạ -----------------------------------------------------
    # Chèn trước phụ đề: thẻ nằm ở giữa khung, phụ đề ở đáy, nướng phụ đề sau
    # cùng thì chữ luôn nằm trên và không bao giờ bị thẻ che.
    current = stitched
    motion_result = motion_service.decorate(
        current, segments, duration, work, settings, render,
        ask_json=_gemini_json if gemini.available() else None,
        on_progress=lambda f, m: manager.progress(
            job.id, "Thẻ đồ hoạ", _span("motion", f), m
        ),
    )
    current = motion_result["video"]

    # --- 6. Phụ đề ---------------------------------------------------------
    lines = align.build_lines(segments, max_chars=settings.subtitle_max_chars)
    srt_path = align.write_srt(lines, out_dir / "phu_de.srt")
    if settings.subtitles and lines:
        manager.progress(job.id, "Ghép video", _span("compose", 0.45), "Đang nướng phụ đề…")
        ass_path = align.write_ass(
            lines,
            work / "subtitle.ass",
            size_percent=settings.subtitle_size,
            two_speakers=speakers >= 2,
        )
        current = compose.burn_subtitles(current, ass_path, work / "with_subs.mp4", render)

    # --- 7. Nhạc nền -------------------------------------------------------
    music_used = ""
    track = music.resolve(settings, plan.get("music_mood", ""))
    if track is not None:
        manager.progress(job.id, "Ghép video", _span("compose", 0.75), f"Trộn nhạc: {track.name}")
        try:
            current = music.mix(current, track, work / "with_music.mp4", duration, settings, render)
            music_used = track.name
        except Exception as exc:  # noqa: BLE001
            # Nhạc là thứ trang trí — hỏng thì vẫn giao video, chỉ ghi lại cảnh báo
            log.warning("Trộn nhạc thất bại (%s) — giữ bản không nhạc.", exc)
    elif settings.music:
        log.info("Thư mục data/music trống — bỏ qua nhạc nền.")

    final = out_dir / "video_doc_9x16.mp4"
    shutil.move(str(current), str(final))
    compose.poster(final, work / "poster.jpg")

    project = {
        "id": job.id,
        "kind": "avatar",
        "title": plan.get("title") or "",
        "engine": engine,
        "speakers": speakers,
        "duration": round(duration, 2),
        "music": music_used,
        "music_mood": plan.get("music_mood", ""),
        "motion_engine": motion_result["engine"],
        "motion_cards": motion_result["cards"],
        "segments": segments,
        "subtitle_lines": lines,
        "portraits": {str(k): v["path"] for k, v in frames.items()},
        "settings": {"avatar": settings.__dict__, "render": render.__dict__},
        "outputs": {"video": final.name, "srt": srt_path.name},
    }
    save_project(job.id, project)

    return {
        "project_id": job.id,
        "title": project["title"],
        "duration": project["duration"],
        "engine": engine,
        "music": music_used,
        "motion_engine": motion_result["engine"],
        "motion_cards": len(motion_result["cards"]),
        "video": final.name,
        "srt": srt_path.name,
        "segments": len(segments),
    }


# ---------------------------------------------------------------------------
# Đường 1: TTS + engine nhép môi chạy local (hoặc ảnh tĩnh)
# ---------------------------------------------------------------------------


def _run_local(
    job: Job,
    plan: dict,
    frames: dict[int, dict],
    settings: AvatarSettings,
    render: RenderSettings,
    work: Path,
    engine: str,
) -> dict:
    manager.progress(job.id, "Đọc lời thoại", _span("voice", 0.05), "Gọi Gemini TTS…")

    spoken = voice.synthesize_segments(
        plan["segments"],
        settings,
        work,
        on_progress=lambda f, m: manager.progress(job.id, "Đọc lời thoại", _span("voice", f), m),
    )
    segments = spoken["segments"]
    shots = voice.build_shots(segments, settings, work)

    clips_dir = work / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []

    for i, shot in enumerate(shots):
        frac = i / max(len(shots), 1)
        speaker_frame = Path(frames.get(shot["speaker"], frames[1])["path"])
        audio = Path(shot["wav"])
        raw = clips_dir / f"raw_{i:03d}.mp4"

        manager.progress(
            job.id, "Nhép môi", _span("lipsync", frac),
            f"Cảnh {i + 1}/{len(shots)} — người {shot['speaker']}",
        )

        if engine == "still":
            lipsync.run_still(speaker_frame, audio, shot["duration"], raw, render)
        else:
            try:
                lipsync.run_local(
                    engine,
                    speaker_frame,
                    audio,
                    shot["duration"],
                    raw,
                    clips_dir / f"work_{i:03d}",
                    on_progress=lambda m, i=i: manager.progress(
                        job.id, "Nhép môi", _span("lipsync", frac), f"Cảnh {i + 1}: {m}"
                    ),
                )
            except lipsync.LipSyncError as exc:
                # Một cảnh hỏng không nên giết cả video: lùi về ảnh tĩnh cho cảnh đó
                log.warning("Cảnh %d nhép môi lỗi (%s) — dùng ảnh tĩnh cho cảnh này.", i, exc)
                lipsync.run_still(speaker_frame, audio, shot["duration"], raw, render)

        clips.append(compose.conform(
            raw,
            clips_dir / f"clip_{i:03d}.mp4",
            render,
            audio=audio,                 # tiếng luôn lấy bản TTS gốc
            duration=shot["duration"],
        ))

    return {"segments": segments, "clips": clips, "duration": spoken["duration"]}


# ---------------------------------------------------------------------------
# Đường 2: Veo tự sinh cả hình lẫn tiếng
# ---------------------------------------------------------------------------


def _run_veo(
    job: Job,
    plan: dict,
    frames: dict[int, dict],
    settings: AvatarSettings,
    render: RenderSettings,
    work: Path,
) -> dict:
    """Veo không nhận audio đầu vào — nó tự đọc lời thoại bằng giọng của nó.

    Nên ở đường này không có bước TTS, và mốc thời gian phụ đề phải đo NGƯỢC lại
    từ độ dài clip Veo thật sự trả về, chứ không tính trước được.
    """
    if not gemini.available():
        raise ValueError("Chế độ Veo cần GEMINI_API_KEY trong file .env.")

    tone = script.STYLE_HINTS.get(settings.style, script.STYLE_HINTS["than_thien"])
    clips_dir = work / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    raw_segments = plan["segments"]
    clips: list[Path] = []
    segments: list[dict] = []
    cursor = 0.0

    for i, seg in enumerate(raw_segments):
        # Mỗi lần gọi Veo chỉ ra được ~8 giây, nên câu quá dài phải cảnh báo
        estimate = script.estimate_seconds(seg["text"])
        if estimate > lipsync.VEO_MAX_SECONDS:
            log.warning(
                "Câu %d dài khoảng %.1fs, vượt giới hạn %.0fs của Veo — có thể bị cụt.",
                i, estimate, lipsync.VEO_MAX_SECONDS,
            )

        frac = i / max(len(raw_segments), 1)
        manager.progress(
            job.id, "Veo dựng video", _span("lipsync", frac),
            f"Câu {i + 1}/{len(raw_segments)}",
        )

        speaker_frame = Path(frames.get(seg.get("speaker", 1), frames[1])["path"])
        raw = clips_dir / f"veo_{i:03d}.mp4"
        lipsync.run_veo(
            speaker_frame,
            seg["text"],
            tone,
            raw,
            emotion=seg.get("emotion", ""),
            on_progress=lambda m, i=i: manager.progress(
                job.id, "Veo dựng video", _span("lipsync", frac), f"Câu {i + 1}: {m}"
            ),
        )

        clip = compose.conform(raw, clips_dir / f"clip_{i:03d}.mp4", render)
        clips.append(clip)

        length = float(probe(clip).get("duration") or estimate)
        segments.append({
            "index": i,
            "speaker": seg.get("speaker", 1),
            "text": seg["text"],
            "emotion": seg.get("emotion", ""),
            "voice": "veo",
            "wav": "",
            "start": round(cursor, 3),
            "end": round(cursor + length, 3),
            "duration": round(length, 3),
        })
        cursor += length

    return {"segments": segments, "clips": clips, "duration": round(cursor, 3)}
