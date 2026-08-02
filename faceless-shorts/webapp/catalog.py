"""Ghép shots.manifest.json (Remotion) với beats.json (dự án) thành một danh mục."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from webapp.config import MANIFEST, OUT_DIR, ROOT, TRACK_DIRS

log = logging.getLogger(__name__)


def _read_json(path: Path) -> Any | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("không đọc được %s: %s", path, e)
        return None


def _projects() -> dict[str, dict]:
    """Quét mọi beats.json, lập chỉ mục theo composition id."""
    found: dict[str, dict] = {}
    for track, base in TRACK_DIRS.items():
        if not base.is_dir():
            continue
        for beats_path in sorted(base.glob("*/beats.json")):
            beats = _read_json(beats_path)
            if not isinstance(beats, dict):
                continue
            comp = beats.get("composition")
            if not comp:
                continue
            folder = beats_path.parent
            found[comp] = {
                "track": track,
                "project": beats.get("id") or folder.name,
                "title": beats.get("title") or folder.name,
                "folder": str(folder.relative_to(ROOT)),
                "has_script": (folder / "script.md").exists(),
                "has_sfx_plan": (folder / "sfx-plan.json").exists(),
                "vo_lines": len(beats.get("vo") or []),
            }
    return found


def shots() -> list[dict]:
    """Danh sách composition kèm metadata dự án và trạng thái file đã render."""
    manifest = _read_json(MANIFEST)
    if not isinstance(manifest, list):
        return []

    projects = _projects()
    out: list[dict] = []
    for entry in manifest:
        comp_id = entry.get("id")
        if not comp_id:
            continue
        proj = projects.get(comp_id, {})
        transparent = bool(entry.get("transparent"))
        video = OUT_DIR / f"{comp_id}.{'mov' if transparent else 'mp4'}"
        still = OUT_DIR / f"{comp_id}.png"

        duration = float(entry.get("durationInSeconds") or 0)
        fps = int(entry.get("fps") or 30)
        out.append(
            {
                "id": comp_id,
                "title": proj.get("title") or comp_id,
                "track": proj.get("track") or "tsx",
                "project": proj.get("project"),
                "folder": proj.get("folder"),
                "width": entry.get("width"),
                "height": entry.get("height"),
                "fps": fps,
                "duration_s": duration,
                "frames": int(round(duration * fps)),
                "transparent": transparent,
                "has_script": proj.get("has_script", False),
                "vo_lines": proj.get("vo_lines", 0),
                "still": still.name if still.exists() else None,
                "video": video.name if video.exists() else None,
                "video_size": video.stat().st_size if video.exists() else 0,
            }
        )
    return out


def shot(comp_id: str) -> dict | None:
    return next((s for s in shots() if s["id"] == comp_id), None)


def script_text(comp_id: str) -> str | None:
    """Nội dung script.md của shot, nếu có."""
    s = shot(comp_id)
    if not s or not s.get("folder"):
        return None
    path = ROOT / s["folder"] / "script.md"
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("không đọc được %s: %s", path, e)
        return None
