"""Gọi Claude và ép trả về JSON đúng schema.

Mọi chỗ dùng AI trong Radar đều đi qua đây. Lỗi API không bao giờ được làm chết
luồng — trả None để bên gọi tự dùng phương án offline.
"""

from __future__ import annotations

import json
import logging

from radar.config import ANTHROPIC_API_KEY, WRITER_MODEL, has_claude

log = logging.getLogger(__name__)


def claude_json(system: str, user: str, schema: dict, max_tokens: int = 8000) -> dict | None:
    if not has_claude():
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=WRITER_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "refusal":
            log.warning("Claude từ chối xử lý nội dung này.")
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(text) if text else None
    except Exception as exc:  # noqa: BLE001 - API hỏng thì rơi về chế độ offline
        log.warning("Gọi Claude thất bại: %s", exc)
        return None
