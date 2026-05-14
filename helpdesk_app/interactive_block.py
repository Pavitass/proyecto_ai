"""Bloque opcional ```helpdesk-ui``` en respuestas del asistente (kanban / sliders en el panel en vivo)."""

from __future__ import annotations

import json
import re

_UI_BLOCK = re.compile(r"```helpdesk-ui\s*([\s\S]*?)```", re.IGNORECASE)


def strip_helpdesk_ui_block(text: str) -> str:
    if not text:
        return text or ""
    return _UI_BLOCK.sub("", text).strip()


def parse_helpdesk_ui_block(text: str) -> dict | None:
    m = _UI_BLOCK.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return None
