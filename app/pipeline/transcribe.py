"""Bóc lời nói bằng faster-whisper (chạy local, có timestamp từng chữ)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from app.config import WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL

log = logging.getLogger(__name__)

_MODEL_CACHE: dict[tuple[str, str, str], object] = {}


def _resolve_device() -> tuple[str, str]:
    """Chọn cuda nếu có, không thì cpu; kèm compute_type phù hợp."""
    device = WHISPER_DEVICE
    if device == "auto":
        device = "cpu"
        try:
            import ctranslate2  # type: ignore

            if ctranslate2.get_cuda_device_count() > 0:
                device = "cuda"
        except Exception:
            pass

    compute = WHISPER_COMPUTE_TYPE
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def _get_model():
    device, compute = _resolve_device()
    key = (WHISPER_MODEL, device, compute)
    if key not in _MODEL_CACHE:
        from faster_whisper import WhisperModel

        log.info("Nạp Whisper %s trên %s (%s)...", WHISPER_MODEL, device, compute)
        try:
            _MODEL_CACHE[key] = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute)
        except Exception as exc:
            if device == "cuda":
                log.warning("Không dùng được GPU (%s), chuyển sang CPU int8.", exc)
                fallback = (WHISPER_MODEL, "cpu", "int8")
                _MODEL_CACHE[key] = _MODEL_CACHE.get(fallback) or WhisperModel(
                    WHISPER_MODEL, device="cpu", compute_type="int8"
                )
            else:
                raise
    return _MODEL_CACHE[key]


def transcribe(
    audio_path: Path,
    language: str | None = "vi",
    on_progress: Callable[[float, str], None] | None = None,
) -> dict:
    """
    Trả về:
        {
          "language": "vi",
          "text": "...",
          "segments": [{"id", "start", "end", "text",
                        "words": [{"start","end","text"}]}]
        }
    """
    model = _get_model()

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=None if language in (None, "", "auto") else language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        beam_size=5,
        condition_on_previous_text=False,
    )

    total = float(getattr(info, "duration", 0.0) or 0.0)
    segments: list[dict] = []
    full_text: list[str] = []

    for idx, seg in enumerate(segments_iter):
        words = []
        for w in (seg.words or []):
            token = (w.word or "").strip()
            if not token:
                continue
            words.append({
                "start": round(float(w.start), 3),
                "end": round(float(w.end), 3),
                "text": token,
            })
        text = (seg.text or "").strip()
        segments.append({
            "id": idx,
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": text,
            "words": words,
        })
        full_text.append(text)

        if on_progress and total > 0:
            on_progress(min(float(seg.end) / total, 1.0), text[:80])

    return {
        "language": getattr(info, "language", language) or "vi",
        "text": " ".join(full_text).strip(),
        "segments": segments,
    }
