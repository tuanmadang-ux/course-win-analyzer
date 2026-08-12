"""Client gọi Google Gemini API.

Chỉ dùng httpx + REST, không cần SDK, để khỏi thêm phụ thuộc nặng. Bốn việc:

* `generate_text`  — viết/biên tập kịch bản, chọn nhạc  (models:generateContent)
* `synthesize`     — đọc thành tiếng                     (generateContent + AUDIO)
* `generate_image` — dựng lại nền / khung hình 9:16      (generateContent + IMAGE)
* `generate_video` — Veo 3.1, ảnh -> video có nhép môi   (predictLongRunning)

Mọi hàm đều ném `GeminiError` với thông điệp tiếng Việt đọc được, vì lỗi ở đây
hầu hết là do key sai / hết quota / model chưa mở cho tài khoản — người dùng cần
biết chính xác cái nào chứ không phải một stack trace.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from app.config import (
    GEMINI_API_KEY,
    GEMINI_IMAGE_MODEL,
    GEMINI_TEXT_MODEL,
    GEMINI_TTS_MODEL,
    GEMINI_VEO_MODEL,
)

log = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta"

# TTS của Gemini luôn trả PCM 16-bit mono 24kHz, không có header wav.
TTS_SAMPLE_RATE = 24_000
TTS_SAMPLE_WIDTH = 2
TTS_CHANNELS = 1

# Danh sách voice dựng sẵn hay dùng. Không phải toàn bộ, nhưng đủ để chọn trong UI.
VOICES: list[dict[str, str]] = [
    {"id": "Charon", "label": "Charon — nam, trầm, chắc chắn"},
    {"id": "Puck", "label": "Puck — nam, trẻ, tươi"},
    {"id": "Fenrir", "label": "Fenrir — nam, khoẻ, dứt khoát"},
    {"id": "Orus", "label": "Orus — nam, điềm đạm"},
    {"id": "Kore", "label": "Kore — nữ, rõ ràng, chuyên nghiệp"},
    {"id": "Aoede", "label": "Aoede — nữ, nhẹ, dễ chịu"},
    {"id": "Leda", "label": "Leda — nữ, trẻ, năng lượng"},
    {"id": "Zephyr", "label": "Zephyr — nữ, sáng, tươi"},
]


class GeminiError(RuntimeError):
    pass


def available() -> bool:
    return bool(GEMINI_API_KEY)


def _require_key() -> str:
    if not GEMINI_API_KEY:
        raise GeminiError(
            "Chưa có GEMINI_API_KEY. Lấy key miễn phí ở https://aistudio.google.com/apikey "
            "rồi điền vào file .env."
        )
    return GEMINI_API_KEY


def _friendly(status: int, body: str) -> str:
    """Đổi lỗi HTTP của Google thành câu tiếng Việt nói rõ phải làm gì."""
    detail = body[:400]
    try:
        detail = json.loads(body).get("error", {}).get("message", detail)
    except Exception:  # noqa: BLE001
        pass

    if status in (401, 403):
        return f"Key Gemini bị từ chối ({status}). Kiểm tra lại GEMINI_API_KEY.\n{detail}"
    if status == 429:
        return (
            "Gemini báo vượt hạn mức (429). Chờ một lát rồi thử lại, hoặc bật thanh toán "
            f"cho project trong Google AI Studio.\n{detail}"
        )
    if status == 404:
        return (
            f"Model không tồn tại hoặc tài khoản chưa được mở quyền dùng.\n{detail}"
        )
    return f"Gemini trả lỗi {status}.\n{detail}"


def _post(path: str, payload: dict, timeout: float = 180.0) -> dict:
    key = _require_key()
    url = f"{BASE}/{path}"
    try:
        resp = httpx.post(
            url,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise GeminiError(f"Không gọi được Gemini API: {exc}") from exc

    if resp.status_code >= 400:
        raise GeminiError(_friendly(resp.status_code, resp.text))
    return resp.json()


def _get(path: str, timeout: float = 60.0) -> dict:
    key = _require_key()
    url = path if path.startswith("http") else f"{BASE}/{path}"
    try:
        resp = httpx.get(url, headers={"x-goog-api-key": key}, timeout=timeout)
    except httpx.HTTPError as exc:
        raise GeminiError(f"Không gọi được Gemini API: {exc}") from exc

    if resp.status_code >= 400:
        raise GeminiError(_friendly(resp.status_code, resp.text))
    return resp.json()


def _parts(data: dict) -> list[dict]:
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback") or {}
        reason = feedback.get("blockReason")
        if reason:
            raise GeminiError(
                f"Gemini từ chối nội dung này (lý do: {reason}). Thử sửa lại lời thoại."
            )
        raise GeminiError("Gemini không trả về nội dung nào.")
    return candidates[0].get("content", {}).get("parts") or []


# ---------------------------------------------------------------------------
# 1. Văn bản
# ---------------------------------------------------------------------------


def generate_text(
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
    model: str = "",
) -> str:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    data = _post(f"models/{model or GEMINI_TEXT_MODEL}:generateContent", payload)
    return "".join(p.get("text", "") for p in _parts(data)).strip()


def generate_json(prompt: str, system: str = "", temperature: float = 0.5) -> Any:
    """Như `generate_text` nhưng ép ra JSON và tự gỡ rào ```json nếu có."""
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    data = _post(f"models/{GEMINI_TEXT_MODEL}:generateContent", payload)
    raw = "".join(p.get("text", "") for p in _parts(data)).strip()

    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.S)
    if fenced:
        raw = fenced.group(1)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GeminiError(f"Gemini trả về JSON hỏng: {raw[:300]}") from exc


# ---------------------------------------------------------------------------
# 2. Đọc thành tiếng
# ---------------------------------------------------------------------------


def synthesize(text: str, voice: str, style_hint: str = "") -> bytes:
    """Trả về PCM 16-bit mono 24kHz (chưa có header wav) cho một đoạn thoại."""
    if not text.strip():
        raise GeminiError("Đoạn thoại rỗng, không đọc được.")

    # Gemini TTS đọc nguyên văn phần sau dấu hai chấm, còn phần trước là chỉ dẫn
    # diễn cảm. Nhờ vậy điều khiển được tốc độ / cảm xúc mà không đọc lẫn chỉ dẫn.
    prompt = f"{style_hint.strip()}: {text.strip()}" if style_hint.strip() else text.strip()

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }
    data = _post(f"models/{GEMINI_TTS_MODEL}:generateContent", payload)

    for part in _parts(data):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])

    raise GeminiError("Gemini TTS không trả về audio. Thử đổi voice hoặc rút ngắn câu.")


# ---------------------------------------------------------------------------
# 3. Ảnh
# ---------------------------------------------------------------------------


def generate_image(prompt: str, images: list[Path] | None = None) -> bytes | None:
    """Sinh/chỉnh ảnh. Trả None nếu model không trả ảnh (không coi là lỗi chết)."""
    parts: list[dict] = []
    for img in images or []:
        parts.append({
            "inlineData": {
                "mimeType": _mime_of(img),
                "data": base64.b64encode(img.read_bytes()).decode("ascii"),
            }
        })
    parts.append({"text": prompt})

    data = _post(
        f"models/{GEMINI_IMAGE_MODEL}:generateContent",
        {"contents": [{"role": "user", "parts": parts}]},
    )
    for part in _parts(data):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    return None


def _mime_of(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".webp": "image/webp",
        ".heic": "image/heic",
    }.get(ext, "image/jpeg")


# ---------------------------------------------------------------------------
# 4. Veo — ảnh + lời thoại -> video 8 giây có tiếng, đã nhép môi
# ---------------------------------------------------------------------------


def generate_video(
    prompt: str,
    image: Path | None = None,
    aspect_ratio: str = "9:16",
    resolution: str = "1080p",
    negative_prompt: str = "",
    poll_interval: float = 8.0,
    max_wait: float = 900.0,
    on_progress: Callable[[str], None] | None = None,
) -> bytes:
    """Gọi Veo rồi chờ tới khi có file. Trả về bytes của mp4."""
    instance: dict[str, Any] = {"prompt": prompt}
    if image is not None:
        instance["image"] = {
            "bytesBase64Encoded": base64.b64encode(image.read_bytes()).decode("ascii"),
            "mimeType": _mime_of(image),
        }

    parameters: dict[str, Any] = {
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
    }
    if negative_prompt:
        parameters["negativePrompt"] = negative_prompt

    op = _post(
        f"models/{GEMINI_VEO_MODEL}:predictLongRunning",
        {"instances": [instance], "parameters": parameters},
        timeout=300.0,
    )
    name = op.get("name")
    if not name:
        raise GeminiError("Veo không trả về mã tác vụ.")

    waited = 0.0
    while waited < max_wait:
        if op.get("done"):
            break
        time.sleep(poll_interval)
        waited += poll_interval
        if on_progress:
            on_progress(f"Veo đang dựng video… {int(waited)}s")
        op = _get(name)

    if not op.get("done"):
        raise GeminiError(f"Veo chạy quá {int(max_wait)}s mà chưa xong. Thử lại sau.")

    if op.get("error"):
        raise GeminiError(f"Veo báo lỗi: {op['error'].get('message', op['error'])}")

    return _download_veo_result(op)


def _download_veo_result(op: dict) -> bytes:
    """Moi mp4 ra khỏi operation. Veo có thể trả base64 hoặc một URI phải tải."""
    response = op.get("response") or {}
    samples = (
        response.get("generatedVideos")
        or response.get("generateVideoResponse", {}).get("generatedSamples")
        or response.get("videos")
        or []
    )
    if not samples:
        raise GeminiError("Veo báo xong nhưng không có video nào trong kết quả.")

    video = samples[0].get("video") or samples[0]

    encoded = video.get("bytesBase64Encoded") or video.get("videoBytes")
    if encoded:
        return base64.b64decode(encoded)

    uri = video.get("uri") or video.get("gcsUri")
    if not uri:
        raise GeminiError("Không tìm thấy đường dẫn video trong kết quả của Veo.")

    key = _require_key()
    try:
        resp = httpx.get(
            uri, headers={"x-goog-api-key": key}, timeout=600.0, follow_redirects=True
        )
    except httpx.HTTPError as exc:
        raise GeminiError(f"Tải video từ Veo thất bại: {exc}") from exc

    if resp.status_code >= 400:
        raise GeminiError(_friendly(resp.status_code, resp.text[:300]))
    return resp.content
