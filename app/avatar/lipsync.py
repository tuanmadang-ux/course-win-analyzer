"""Nhép môi: cho ảnh chân dung + file tiếng, trả về video người đó đang nói.

Có bốn đường, xếp theo thứ tự ưu tiên khi để `LIPSYNC_ENGINE=auto`:

1. `latentsync`  — chất lượng cao nhất, chạy local, miễn phí. Cần GPU + repo đã clone.
2. `sadtalker`   — cũng local, nhẹ hơn, thêm cử động đầu tự nhiên.
3. `wav2lip`     — cũ nhất nhưng nhẹ và ổn định, hợp máy yếu.
4. `veo`         — gọi Gemini. KHÔNG nhận file tiếng của ta: Veo tự đọc lời thoại
                   bằng giọng của nó, nên đường này thay luôn cả phần TTS.
5. `still`       — không nhép môi, chỉ zoom chậm ảnh tĩnh. Luôn chạy được, dùng làm
                   lưới an toàn để phần mềm không bao giờ tắc ở bước cuối.

Ba engine local đều là repo bên ngoài, không thể đóng gói kèm. Ở đây chỉ định
nghĩa cách gọi chúng qua dòng lệnh; `setup_lipsync.sh` lo phần tải về.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import (
    FFMPEG,
    LIPSYNC_ENGINE,
    LIPSYNC_HOME,
    LIPSYNC_PYTHON,
    LIPSYNC_TIMEOUT,
    RenderSettings,
)
from app.pipeline.ffmpeg_utils import run
from app.pipeline.render import VENC, run_encode

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]

FPS = 25.0  # cả ba model local đều được huấn luyện ở 25fps


class LipSyncError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Khai báo cách gọi từng repo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineSpec:
    name: str
    label: str
    folder: str            # tên thư mục trong LIPSYNC_HOME
    entry: str             # file phải tồn tại thì mới coi là đã cài
    needs_video_input: bool  # True: phải biến ảnh thành video tĩnh trước


ENGINES: dict[str, EngineSpec] = {
    "latentsync": EngineSpec(
        name="latentsync",
        label="LatentSync — nét nhất, cần GPU ≥8GB",
        folder="LatentSync",
        entry="scripts/inference.py",
        needs_video_input=True,
    ),
    "sadtalker": EngineSpec(
        name="sadtalker",
        label="SadTalker — có cử động đầu, nhẹ hơn",
        folder="SadTalker",
        entry="inference.py",
        needs_video_input=False,
    ),
    "wav2lip": EngineSpec(
        name="wav2lip",
        label="Wav2Lip — nhẹ nhất, chạy được máy yếu",
        folder="Wav2Lip",
        entry="inference.py",
        needs_video_input=False,
    ),
}

PREFERENCE = ["latentsync", "sadtalker", "wav2lip"]


def engine_dir(spec: EngineSpec) -> Path:
    return LIPSYNC_HOME / spec.folder


def is_installed(spec: EngineSpec) -> bool:
    return (engine_dir(spec) / spec.entry).is_file()


def installed_engines() -> list[str]:
    return [name for name in PREFERENCE if is_installed(ENGINES[name])]


def resolve_engine(requested: str = "") -> str:
    """Chốt engine sẽ dùng. Trả về tên engine, luôn trả về một giá trị hợp lệ."""
    choice = (requested or LIPSYNC_ENGINE or "auto").strip().lower()

    if choice in ("veo", "still"):
        return choice

    if choice in ENGINES:
        if is_installed(ENGINES[choice]):
            return choice
        raise LipSyncError(
            f"Chưa cài {ENGINES[choice].label}. Chạy `bash setup_lipsync.sh {choice}` "
            f"hoặc đổi engine trong giao diện."
        )

    found = installed_engines()
    if found:
        return found[0]

    log.warning("Chưa cài engine nhép môi nào — tạm dùng chế độ ảnh tĩnh.")
    return "still"


def describe() -> list[dict]:
    """Danh sách engine + trạng thái, cho giao diện hiển thị."""
    from app.avatar import gemini  # noqa: PLC0415  (tránh vòng import lúc nạp module)

    items = [
        {
            "id": name,
            "label": spec.label,
            "ready": is_installed(spec),
            "hint": "" if is_installed(spec) else f"bash setup_lipsync.sh {name}",
        }
        for name, spec in ENGINES.items()
    ]
    items.append({
        "id": "veo",
        "label": "Veo 3.1 (Gemini) — không cần cài, Veo tự đọc lời thoại",
        "ready": gemini.available(),
        "hint": "" if gemini.available() else "cần GEMINI_API_KEY",
    })
    items.append({
        "id": "still",
        "label": "Ảnh tĩnh zoom chậm — không nhép môi",
        "ready": True,
        "hint": "",
    })
    return items


# ---------------------------------------------------------------------------
# Chạy engine local
# ---------------------------------------------------------------------------


def _python() -> str:
    return LIPSYNC_PYTHON or sys.executable


def _argv(spec: EngineSpec, face: Path, audio: Path, out: Path, work: Path) -> list[str]:
    root = engine_dir(spec)
    if spec.name == "latentsync":
        return [
            _python(), str(root / "scripts" / "inference.py"),
            "--unet_config_path", str(root / "configs" / "unet" / "stage2.yaml"),
            "--inference_ckpt_path", str(root / "checkpoints" / "latentsync_unet.pt"),
            "--video_path", str(face),
            "--audio_path", str(audio),
            "--video_out_path", str(out),
        ]
    if spec.name == "sadtalker":
        return [
            _python(), str(root / "inference.py"),
            "--driven_audio", str(audio),
            "--source_image", str(face),
            "--result_dir", str(work),
            "--preprocess", "full",
            "--still",
            "--expression_scale", "1.1",
        ]
    if spec.name == "wav2lip":
        return [
            _python(), str(root / "inference.py"),
            "--checkpoint_path", str(root / "checkpoints" / "wav2lip_gan.pth"),
            "--face", str(face),
            "--audio", str(audio),
            "--outfile", str(out),
            "--resize_factor", "1",
            "--pads", "0", "12", "0", "0",
            # Wav2Lip mặc định 25fps, tình cờ trùng FPS của ta. Truyền thẳng để
            # nếu sau này đổi FPS thì hai bên không lệch nhau trong im lặng.
            "--fps", f"{FPS:g}",
            # Mặc định của repo là 128 — nặng với card 8GB khi khung hình 1080x1920.
            # 64 chậm hơn một chút nhưng ít hết VRAM hơn nhiều.
            "--wav2lip_batch_size", "64",
        ]
    raise LipSyncError(f"Chưa biết cách gọi engine {spec.name}.")


def _still_video(image: Path, duration: float, dest: Path) -> Path:
    """Ảnh -> video tĩnh đúng độ dài, làm đầu vào cho model cần video."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image),
        "-t", f"{max(duration, 0.1):.3f}",
        "-r", f"{FPS:g}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(dest),
    ])
    return dest


def _newest_mp4(folder: Path, after: float) -> Path | None:
    candidates = [
        p for p in folder.rglob("*.mp4")
        if p.is_file() and p.stat().st_mtime >= after - 1
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def run_local(
    engine: str,
    portrait: Path,
    audio: Path,
    duration: float,
    dest: Path,
    work_dir: Path,
    on_progress: ProgressFn | None = None,
) -> Path:
    """Gọi một repo lip-sync qua dòng lệnh và trả về file mp4 kết quả."""
    spec = ENGINES[engine]
    root = engine_dir(spec)
    if not is_installed(spec):
        raise LipSyncError(f"Chưa cài {spec.label}. Chạy: bash setup_lipsync.sh {engine}")

    work_dir.mkdir(parents=True, exist_ok=True)
    face: Path = portrait
    if spec.needs_video_input:
        if on_progress:
            on_progress("Dựng khung hình nền cho model…")
        face = _still_video(portrait, duration, work_dir / "still_input.mp4")

    started = time.time()
    argv = _argv(spec, face, audio, dest, work_dir)

    if on_progress:
        on_progress(f"Đang nhép môi bằng {spec.name}…")
    log.info("Chạy %s: %s", spec.name, " ".join(argv[:3]))

    try:
        proc = subprocess.run(
            argv,
            cwd=str(root),          # các repo này đều dùng đường dẫn tương đối
            capture_output=True,
            text=True,
            timeout=LIPSYNC_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise LipSyncError(
            f"{spec.name} chạy quá {LIPSYNC_TIMEOUT}s. Thử nội dung ngắn hơn, "
            f"hoặc tăng LIPSYNC_TIMEOUT trong .env."
        ) from exc
    except FileNotFoundError as exc:
        raise LipSyncError(f"Không chạy được Python cho {spec.name}: {exc}") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise LipSyncError(f"{spec.name} chạy lỗi:\n{tail}")

    if not dest.exists():
        # SadTalker tự đặt tên file theo thời gian, phải đi tìm
        found = _newest_mp4(work_dir, started)
        if not found:
            tail = (proc.stdout or "")[-800:]
            raise LipSyncError(f"{spec.name} chạy xong nhưng không thấy file video.\n{tail}")
        shutil.move(str(found), str(dest))

    return dest


# ---------------------------------------------------------------------------
# Chế độ ảnh tĩnh (luôn dùng được)
# ---------------------------------------------------------------------------


def run_still(
    portrait: Path,
    audio: Path,
    duration: float,
    dest: Path,
    settings: RenderSettings,
    zoom_per_second: float = 0.008,
) -> Path:
    """Zoom chậm vào ảnh (hiệu ứng Ken Burns) và ghép tiếng vào."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames = max(int(round(duration * FPS)), 2)
    # zoompan tính theo số khung, nên quy đổi tốc độ zoom sang từng khung
    step = zoom_per_second / FPS

    vf = (
        f"scale=2160:-2,"
        f"zoompan=z='min(zoom+{step:.6f},1.15)':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS:g},"
        f"setsar=1"
    )
    run_encode([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(portrait),
        "-i", str(audio),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        VENC,
        "-c:a", "aac", "-b:a", settings.audio_bitrate, "-ar", "48000", "-ac", "2",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        str(dest),
    ], settings)
    return dest


# ---------------------------------------------------------------------------
# Veo
# ---------------------------------------------------------------------------

VEO_MAX_SECONDS = 8.0


def veo_prompt(text: str, style: str, emotion: str = "") -> str:
    """Prompt cho Veo. Lời thoại đặt trong ngoặc kép để Veo đọc và nhép môi theo."""
    mood = f" Nét mặt {emotion}." if emotion else ""
    return (
        f"Chân dung người trong ảnh đang nói thẳng vào máy quay, quay dọc, cận vai. "
        f"Giữ nguyên khuôn mặt, kiểu tóc và trang phục của người trong ảnh. "
        f"Ánh sáng mềm, nền giữ nguyên, máy quay đứng yên. "
        f"Giọng điệu {style}.{mood} "
        f'Người đó nói: "{text}"'
    )


def run_veo(
    portrait: Path,
    text: str,
    style: str,
    dest: Path,
    emotion: str = "",
    on_progress: ProgressFn | None = None,
) -> Path:
    from app.avatar import gemini  # noqa: PLC0415

    data = gemini.generate_video(
        veo_prompt(text, style, emotion),
        image=portrait,
        aspect_ratio="9:16",
        on_progress=(lambda m: on_progress(m)) if on_progress else None,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest
