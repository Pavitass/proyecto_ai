"""Trazas por petición HTTP: fuentes KB/web para la respuesta y depuración."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_trace: ContextVar[dict[str, Any] | None] = ContextVar("helpdesk_chat_trace", default=None)


def trace_begin() -> object:
    data: dict[str, Any] = {"kb_sources": [], "web_sources": []}
    return _trace.set(data)


def trace_reset(token: object) -> None:
    _trace.reset(token)


def _get() -> dict[str, Any]:
    t = _trace.get()
    if t is None:
        return {"kb_sources": [], "web_sources": []}
    return t


def add_kb_source(source: str, preview: str = "") -> None:
    src = (source or "").strip()
    if not src:
        return
    prev = (preview or "").strip().replace("\n", " ")[:220]
    _get()["kb_sources"].append({"kind": "kb", "source": src, "preview": prev})


def add_web_source(title: str, url: str, snippet: str = "") -> None:
    _get()["web_sources"].append(
        {
            "kind": "web",
            "title": (title or "").strip()[:200],
            "url": (url or "").strip()[:500],
            "snippet": (snippet or "").strip().replace("\n", " ")[:320],
        }
    )


def snapshot() -> dict[str, list]:
    t = _get()
    return {"kb_sources": list(t["kb_sources"]), "web_sources": list(t["web_sources"])}
