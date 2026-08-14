"""Gọi HyperFrames hoặc Remotion để render một thẻ thành video có kênh alpha.

Hai engine làm cùng một việc theo hai cách:

* **HyperFrames** (Apache 2.0, HeyGen) — thẻ là HTML thường, dữ liệu truyền vào
  bằng `--variables`. Không giới hạn quy mô công ty.
* **Remotion** — thẻ là component React. Mạnh và trưởng thành hơn, nhưng giấy
  phép chỉ miễn phí cho cá nhân và công ty **từ 3 người trở xuống**; đông hơn
  phải mua license công ty ở remotion.pro.

Vì lý do giấy phép, `auto` luôn ưu tiên HyperFrames.

Cả hai đều xuất MOV ProRes 4444 nền trong suốt, dài cố định (`CARD_SECONDS`).
Việc kéo dài thẻ cho vừa ô thời gian và làm mờ dần lúc kết do `overlay.py` lo —
làm vậy thì mỗi thẻ chỉ phải render đúng phần chuyển động đầu, nhanh hơn nhiều
so với render đủ độ dài thật.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import (
    MOTION_ENGINE,
    MOTION_HOME,
    MOTION_TIMEOUT,
    NPX_BIN,
    REMOTION_BROWSER,
)

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]

# Độ dài mỗi thẻ được render ra. Chỉ cần đủ cho hiệu ứng vào + một nhịp giữ.
CARD_SECONDS = 3.0


class MotionError(RuntimeError):
    pass


@dataclass(frozen=True)
class EngineSpec:
    id: str
    label: str
    project: str        # thư mục dự án con trong app/motion/
    marker: str         # file phải tồn tại thì mới coi là đã cài xong


ENGINES: dict[str, EngineSpec] = {
    "hyperframes": EngineSpec(
        id="hyperframes",
        label="HyperFrames — Apache 2.0, dùng thương mại thoải mái",
        project="project",
        marker="node_modules/gsap/dist/gsap.min.js",
    ),
    "remotion": EngineSpec(
        id="remotion",
        label="Remotion — miễn phí cho cá nhân & công ty ≤3 người, đông hơn phải mua license",
        project="remotion",
        marker="node_modules/remotion/package.json",
    ),
}

PREFERENCE = ["hyperframes", "remotion"]


def project_dir(spec: EngineSpec) -> Path:
    return MOTION_HOME / spec.project


def is_installed(spec: EngineSpec) -> bool:
    return (project_dir(spec) / spec.marker).is_file()


def node_available() -> bool:
    return shutil.which(NPX_BIN) is not None


def installed_engines() -> list[str]:
    return [name for name in PREFERENCE if is_installed(ENGINES[name])]


def resolve(requested: str = "") -> str:
    """Chốt engine sẽ dùng. Trả 'off' khi không có gì chạy được."""
    choice = (requested or MOTION_ENGINE or "auto").strip().lower()
    if choice == "off":
        return "off"

    if not node_available():
        log.warning("Không tìm thấy Node.js — bỏ qua thẻ đồ hoạ.")
        return "off"

    if choice in ENGINES:
        if is_installed(ENGINES[choice]):
            return choice
        raise MotionError(
            f"Chưa cài {ENGINES[choice].label}. Chạy: bash setup_motion.sh {choice}"
        )

    found = installed_engines()
    if found:
        return found[0]

    log.warning("Chưa cài engine đồ hoạ nào — bỏ qua thẻ B-roll.")
    return "off"


def resolve_safe() -> str:
    """Như `resolve` nhưng không bao giờ ném lỗi — dùng cho endpoint trạng thái."""
    try:
        return resolve()
    except MotionError:
        return "off"


def describe() -> list[dict]:
    """Trạng thái từng engine, cho giao diện hiển thị."""
    has_node = node_available()
    items = [
        {
            "id": name,
            "label": spec.label,
            "ready": has_node and is_installed(spec),
            "hint": (
                "cần cài Node.js 22+" if not has_node
                else "" if is_installed(spec)
                else f"bash setup_motion.sh {name}"
            ),
            "license_warning": name == "remotion",
        }
        for name, spec in ENGINES.items()
    ]
    items.append({
        "id": "off",
        "label": "Tắt — không chèn thẻ đồ hoạ",
        "ready": True,
        "hint": "",
        "license_warning": False,
    })
    return items


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _run(argv: list[str], cwd: Path, what: str) -> None:
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, timeout=MOTION_TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        raise MotionError(f"{what} chạy quá {MOTION_TIMEOUT}s.") from exc
    except FileNotFoundError as exc:
        raise MotionError(f"Không chạy được {NPX_BIN}: {exc}") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1200:]
        raise MotionError(f"{what} lỗi:\n{tail}")


def _remotion_id(card_type: str) -> str:
    """Remotion chỉ cho phép chữ, số và dấu gạch ngang trong id composition.

    Tên loại thẻ bên Python dùng gạch dưới (`lower_third`), nên phải quy đổi ở
    đây thay vì bắt cả hệ thống đổi theo một ràng buộc của riêng một engine.
    """
    return card_type.replace("_", "-")


def render_card(
    engine: str,
    card_type: str,
    variables: dict,
    dest: Path,
    on_progress: ProgressFn | None = None,
) -> Path:
    """Render một thẻ ra MOV nền trong suốt 1080x1920."""
    if engine not in ENGINES:
        raise MotionError(f"Không biết engine đồ hoạ '{engine}'.")

    spec = ENGINES[engine]
    root = project_dir(spec)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress(f"Dựng thẻ {card_type} bằng {engine}…")

    if engine == "hyperframes":
        argv = [
            NPX_BIN, "hyperframes", "render", ".",
            "-c", f"compositions/{card_type}.html",
            "--variables", json.dumps(variables, ensure_ascii=False),
            "--format", "mov",
            "-o", str(dest.resolve()),
            "--quiet",
        ]
    else:
        argv = [
            NPX_BIN, "remotion", "render",
            "src/index.ts", _remotion_id(card_type), str(dest.resolve()),
            "--props", json.dumps(variables, ensure_ascii=False),
            "--codec", "prores",
            "--prores-profile", "4444",
            "--pixel-format", "yuva444p10le",
            "--log", "error",
        ]
        if REMOTION_BROWSER:
            argv += ["--browser-executable", REMOTION_BROWSER]

    _run(argv, root, f"{engine} render {card_type}")

    if not dest.is_file():
        raise MotionError(f"{engine} chạy xong nhưng không thấy file {dest.name}.")
    return dest
