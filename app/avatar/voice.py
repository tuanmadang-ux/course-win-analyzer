"""Đọc kịch bản thành tiếng bằng Gemini TTS.

Mỗi câu thoại thành một file wav riêng. Nhờ đọc từng câu mà biết được thời lượng
CHÍNH XÁC của từng câu — đó là thứ dùng để canh phụ đề và để cắt cảnh giữa hai
người nói, không phải đoán mò.
"""

from __future__ import annotations

import logging
import re
import time
import wave
from pathlib import Path
from typing import Callable

from app.avatar import gemini, script
from app.avatar.gemini import TTS_CHANNELS, TTS_SAMPLE_RATE, TTS_SAMPLE_WIDTH
from app.config import AvatarSettings

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]

# Hạn mức miễn phí của Gemini TTS là 3 lượt/phút, mà mỗi câu thoại là một lượt.
# Nên chạm trần là chuyện BÌNH THƯỜNG với kịch bản dài, không phải sự cố: cứ chờ
# đúng khoảng server bảo rồi đọc tiếp. Chờ mặc định phải hơn 60 giây, vì cửa sổ
# tính hạn mức của Google dài một phút — chờ ngắn hơn là chạm trần lại ngay.
MAX_RETRIES = 5
RETRY_WAIT = 62.0

# Google gợi ý sẵn thời gian chờ trong thông báo lỗi, ví dụ "retry in 58.5s"
# hoặc "retryDelay": "58s". Bám theo con số đó thì chờ vừa đủ, không phí thời gian.
RETRY_HINT = re.compile(r'retry(?:\s+in|Delay"?:\s*"?)\s*([\d.]+)\s*s', re.I)


def write_wav(pcm: bytes, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as fh:
        fh.setnchannels(TTS_CHANNELS)
        fh.setsampwidth(TTS_SAMPLE_WIDTH)
        fh.setframerate(TTS_SAMPLE_RATE)
        fh.writeframes(pcm)
    return dest


def pcm_duration(pcm: bytes) -> float:
    return len(pcm) / float(TTS_SAMPLE_RATE * TTS_SAMPLE_WIDTH * TTS_CHANNELS)


def _silence(seconds: float) -> bytes:
    frames = int(round(max(seconds, 0.0) * TTS_SAMPLE_RATE))
    return b"\x00" * (frames * TTS_SAMPLE_WIDTH * TTS_CHANNELS)


def _speak(
    text: str,
    voice: str,
    hint: str,
    on_wait: Callable[[float], None] | None = None,
) -> bytes:
    """Gọi TTS, chờ và thử lại khi chạm hạn mức."""
    last: Exception | None = None
    for _attempt in range(MAX_RETRIES):
        try:
            return gemini.synthesize(text, voice=voice, style_hint=hint)
        except gemini.GeminiError as exc:
            last = exc
            message = str(exc)
            if "429" not in message and "hạn mức" not in message:
                raise

            found = RETRY_HINT.search(message)
            wait = min(float(found.group(1)) + 2.0, 180.0) if found else RETRY_WAIT

            log.warning("TTS chạm hạn mức, chờ %.0fs rồi đọc tiếp…", wait)
            if on_wait:
                on_wait(wait)
            time.sleep(wait)

    raise last or gemini.GeminiError(
        "Đọc thoại thất bại sau nhiều lần thử. Hạn mức miễn phí của Gemini TTS là "
        "3 lượt/phút — kịch bản dài nên bật thanh toán trong Google AI Studio, "
        "hoặc rút ngắn nội dung lại."
    )


def synthesize_segments(
    segments: list[dict],
    settings: AvatarSettings,
    work_dir: Path,
    on_progress: ProgressFn | None = None,
) -> dict:
    """Đọc từng câu, ghi wav, và trả về mốc thời gian trên trục video.

    Trả về:
        {
          "segments": [{index, speaker, text, wav, start, end, duration}],
          "narration": Path (toàn bộ giọng nói đã nối, kể cả khoảng nghỉ),
          "duration": float
        }
    """
    if not segments:
        raise ValueError("Kịch bản chưa có câu thoại nào.")

    voice_dir = work_dir / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    hint = script.style_hint(settings)
    gap = _silence(settings.segment_gap)

    timed: list[dict] = []
    track: list[bytes] = []
    cursor = 0.0

    for i, seg in enumerate(segments):
        voice = settings.voice_b if seg.get("speaker") == 2 else settings.voice_a
        seg_hint = hint
        if seg.get("emotion"):
            seg_hint = f"{hint}, cảm xúc {seg['emotion']}"

        # Báo rõ đang chờ hạn mức, nếu không thanh tiến độ đứng im cả phút và
        # người dùng tưởng phần mềm treo rồi tắt đi giữa chừng.
        def _waiting(seconds: float, i=i) -> None:
            if on_progress:
                on_progress(
                    i / len(segments),
                    f"Chạm hạn mức Gemini, chờ {seconds:.0f}s rồi đọc tiếp "
                    f"(câu {i + 1}/{len(segments)})",
                )

        pcm = _speak(seg["text"], voice, seg_hint, on_wait=_waiting)
        duration = pcm_duration(pcm)

        wav_path = voice_dir / f"seg_{i:03d}.wav"
        write_wav(pcm, wav_path)

        timed.append({
            "index": i,
            "speaker": seg.get("speaker", 1),
            "text": seg["text"],
            "emotion": seg.get("emotion", ""),
            "voice": voice,
            "wav": str(wav_path),
            "start": round(cursor, 3),
            "end": round(cursor + duration, 3),
            "duration": round(duration, 3),
        })

        track.append(pcm)
        cursor += duration

        # Chỉ chèn khoảng nghỉ GIỮA các câu, không thêm đuôi thừa ở cuối video
        if i < len(segments) - 1:
            track.append(gap)
            cursor += settings.segment_gap

        if on_progress:
            on_progress((i + 1) / len(segments), f"Đọc câu {i + 1}/{len(segments)}")

    narration = write_wav(b"".join(track), work_dir / "narration.wav")

    return {
        "segments": timed,
        "narration": str(narration),
        "duration": round(cursor, 3),
    }


def build_shots(timed: list[dict], settings: AvatarSettings, work_dir: Path) -> list[dict]:
    """Gộp các câu liên tiếp CÙNG một người nói thành một cảnh quay.

    Model nhép môi tốn vài chục giây mỗi lần gọi, nên gọi một lần cho cả tràng
    nói của một người rẻ hơn nhiều so với gọi từng câu. Chỉ cắt cảnh khi thật sự
    đổi người nói.
    """
    if not timed:
        return []

    shot_dir = work_dir / "shots"
    shot_dir.mkdir(parents=True, exist_ok=True)

    groups: list[list[dict]] = [[timed[0]]]
    for seg in timed[1:]:
        if seg["speaker"] == groups[-1][-1]["speaker"]:
            groups[-1].append(seg)
        else:
            groups.append([seg])

    gap = _silence(settings.segment_gap)
    shots: list[dict] = []

    for i, group in enumerate(groups):
        chunks: list[bytes] = []
        for j, seg in enumerate(group):
            with wave.open(seg["wav"], "rb") as fh:
                chunks.append(fh.readframes(fh.getnframes()))
            if j < len(group) - 1:
                chunks.append(gap)

        # Khoảng nghỉ ngăn cách cảnh này với cảnh sau phải nằm TRONG cảnh này.
        # Bỏ nó đi thì tổng độ dài các cảnh ngắn hơn trục thời gian đã tính cho
        # phụ đề, và phụ đề sẽ trôi dần một nhịp nghỉ sau mỗi lần đổi người nói.
        if i < len(groups) - 1:
            chunks.append(gap)

        pcm = b"".join(chunks)
        wav_path = write_wav(pcm, shot_dir / f"shot_{i:03d}.wav")

        shots.append({
            "index": i,
            "speaker": group[0]["speaker"],
            "wav": str(wav_path),
            "start": group[0]["start"],
            "end": round(group[0]["start"] + pcm_duration(pcm), 3),
            "duration": round(pcm_duration(pcm), 3),
            "text": " ".join(s["text"] for s in group),
            "emotion": group[0].get("emotion", ""),
            "segment_indexes": [s["index"] for s in group],
        })

    return shots
