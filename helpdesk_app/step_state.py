"""Estado en memoria de pasos por hilo (thread_id → message_id → [steps])."""
from __future__ import annotations

from threading import Lock
from typing import Literal

Status = Literal["pending", "done", "stuck"]
_ALLOWED_STATUS: frozenset[str] = frozenset({"pending", "done", "stuck"})

_STORE: dict[str, dict[str, list[dict]]] = {}
_LOCK = Lock()

_ICON = {"pending": "◯", "done": "✓", "stuck": "✕"}


def upsert_steps(thread_id: str, message_id: str, steps: list[dict]) -> None:
    """Replace the steps for (thread_id, message_id). Existing statuses for this message are dropped."""
    normalized: list[dict] = []
    for s in steps:
        normalized.append({
            "index": int(s["index"]),
            "text": str(s.get("text", ""))[:500],
            "status": "pending",
            "note": "",
        })
    with _LOCK:
        _STORE.setdefault(thread_id, {})[message_id] = normalized


def update_step(thread_id: str, message_id: str, index: int, status: str, note: str = "") -> bool:
    if status not in _ALLOWED_STATUS:
        raise ValueError(f"status inválido: {status}")
    with _LOCK:
        msgs = _STORE.get(thread_id)
        if not msgs:
            return False
        steps = msgs.get(message_id)
        if not steps:
            return False
        for s in steps:
            if s["index"] == index:
                s["status"] = status
                s["note"] = str(note or "")[:500]
                return True
        return False


def get_steps(thread_id: str) -> dict[str, list[dict]]:
    with _LOCK:
        msgs = _STORE.get(thread_id, {})
        return {k: [dict(s) for s in v] for k, v in msgs.items()}


def render_status_block(thread_id: str) -> str:
    snapshot = get_steps(thread_id)
    if not snapshot:
        return ""
    lines = ["[Estado de pasos]"]
    for msg_id, steps in snapshot.items():
        if not steps:
            continue
        parts: list[str] = []
        stuck_notes: list[str] = []
        for s in steps:
            icon = _ICON.get(s["status"], "◯")
            parts.append(f"{s['index'] + 1}{icon}")
            if s["status"] == "stuck" and s["note"]:
                stuck_notes.append(f"paso {s['index'] + 1}: {s['note']}")
        line = f"  {msg_id}: " + ", ".join(parts)
        if stuck_notes:
            line += " — atascos: " + "; ".join(stuck_notes)
        lines.append(line)
    return "\n".join(lines)


def clear_thread(thread_id: str) -> None:
    with _LOCK:
        _STORE.pop(thread_id, None)


def clear_all() -> None:
    with _LOCK:
        _STORE.clear()
