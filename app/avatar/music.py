"""Chọn nhạc nền và trộn xuống dưới giọng nói.

Phần mềm KHÔNG tự sinh nhạc — nhạc có bản quyền, sinh ra cũng không dùng thương
mại được. Thay vào đó nó đọc các file nhạc bạn tự bỏ vào `data/music/`, và nhờ
Gemini chọn file hợp tâm trạng video nhất dựa trên tên file. Nên đặt tên file mô
tả một chút, ví dụ `upbeat-corporate-motivation.mp3`.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from app.avatar import gemini
from app.config import FFMPEG, FFPROBE, MUSIC_DIR, AvatarSettings, RenderSettings
from app.pipeline.render import run_encode

log = logging.getLogger(__name__)

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".opus"}

FADE_OUT = 1.8


def library() -> list[dict]:
    """Danh sách nhạc có sẵn trong thư mục data/music."""
    if not MUSIC_DIR.exists():
        return []
    items = [
        {"name": p.name, "label": _pretty(p.stem)}
        for p in sorted(MUSIC_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in AUDIO_EXT
    ]
    return items


def _pretty(stem: str) -> str:
    return re.sub(r"[_-]+", " ", stem).strip().title()


def resolve(settings: AvatarSettings, mood: str) -> Path | None:
    """Chốt file nhạc sẽ dùng: người dùng chọn tay > Gemini chọn > file đầu tiên."""
    if not settings.music:
        return None

    tracks = library()
    if not tracks:
        return None

    if settings.music_file:
        chosen = MUSIC_DIR / Path(settings.music_file).name
        if chosen.is_file():
            return chosen
        log.warning("Không thấy file nhạc %s — chọn lại tự động.", settings.music_file)

    if mood and gemini.available() and len(tracks) > 1:
        picked = _ask_gemini(tracks, mood)
        if picked:
            return picked

    return MUSIC_DIR / tracks[0]["name"]


def _ask_gemini(tracks: list[dict], mood: str) -> Path | None:
    listing = "\n".join(f"{i}. {t['name']}" for i, t in enumerate(tracks))
    prompt = (
        f"Video cần nhạc nền có cảm giác: {mood}\n\n"
        f"Danh sách file nhạc đang có:\n{listing}\n\n"
        f'Chọn ĐÚNG MỘT file hợp nhất. Trả JSON: {{"index": <số thứ tự>}}'
    )
    try:
        data = gemini.generate_json(prompt, temperature=0.2)
        index = int(data.get("index"))
        if 0 <= index < len(tracks):
            return MUSIC_DIR / tracks[index]["name"]
    except Exception as exc:  # noqa: BLE001
        log.warning("Gemini không chọn được nhạc (%s) — lấy file đầu tiên.", exc)
    return None


def mix(
    video: Path,
    track: Path,
    dest: Path,
    duration: float,
    settings: AvatarSettings,
    render: RenderSettings,
) -> Path:
    """Trộn nhạc xuống dưới giọng nói, có fade cuối và (tuỳ chọn) tự né tiếng nói.

    `sidechaincompress` hạ nhạc mỗi khi có tiếng nói — nghe chuyên nghiệp hơn hẳn
    so với để nhạc chạy đều một mức. Giọng nói vừa làm tín hiệu điều khiển vừa là
    thứ được nghe, nên phải tách nó ra hai nhánh trước.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fade_start = max(duration - FADE_OUT, 0.0)

    music_chain = (
        f"[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        f"atrim=0:{duration:.3f},"
        f"volume={settings.music_gain_db:.1f}dB,"
        f"afade=t=in:st=0:d=1.2,afade=t=out:st={fade_start:.3f}:d={FADE_OUT}[music]"
    )

    if settings.music_duck:
        filter_complex = (
            f"[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"asplit=2[voice][key];"
            f"{music_chain};"
            f"[music][key]sidechaincompress=threshold=0.04:ratio=8:attack=15:release=320[ducked];"
            f"[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]"
        )
    else:
        filter_complex = (
            f"[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[voice];"
            f"{music_chain};"
            f"[voice][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]"
        )

    run_encode([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-stream_loop", "-1", "-i", str(track),
        "-filter_complex", filter_complex,
        "-map", "0:v:0", "-map", "[out]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", render.audio_bitrate, "-ar", "48000", "-ac", "2",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        str(dest),
    ], render)
    return dest


def save_upload(data: bytes, filename: str) -> Path:
    """Lưu file nhạc người dùng tải lên vào thư viện."""
    name = Path(filename).name or "nhac.mp3"
    if Path(name).suffix.lower() not in AUDIO_EXT:
        raise ValueError(f"Định dạng nhạc {Path(name).suffix or '(không rõ)'} chưa hỗ trợ.")

    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    dest = MUSIC_DIR / name
    counter = 1
    while dest.exists():
        dest = MUSIC_DIR / f"{Path(name).stem}_{counter}{Path(name).suffix}"
        counter += 1

    dest.write_bytes(data)
    return dest


def probe_duration(path: Path) -> float:
    """Độ dài file nhạc, dùng để cảnh báo nhạc ngắn hơn video (sẽ bị lặp).

    Không dùng được `ffmpeg_utils.probe` vì hàm đó đòi phải có luồng hình.
    """
    proc = subprocess.run(
        [
            FFPROBE, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return 0.0
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return 0.0
