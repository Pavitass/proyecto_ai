"""Bloque opcional ```helpdesk-ui``` en respuestas del asistente (kanban / sliders / survey / choice)."""

from __future__ import annotations

import json
import re

_UI_BLOCK = re.compile(r"```helpdesk-ui\s*([\s\S]*?)```", re.IGNORECASE)

# Frases del asistente que indican que está pidiendo información sin emitir bloque
_INFO_REQUEST_PATTERNS = [
    r"\bind[ií]came\b",
    r"\bdime los? (datos|detalles)\b",
    r"\bresp[oó]ndeme\b",
    r"\bdame los? (datos|detalles)\b",
    r"\bnecesito (que me digas|los? datos|los? detalles|saber)\b",
    r"\bpor favor (ind[ií]came|d[ií]me)\b",
    r"\bel formulario (que (te|le) (puse|adjunt[oé])|de (diagn[oó]stico|abajo))\b",
    r"\bresponder? al formulario\b",
    r"\b¿?responde[s]? al? formulario\b",
]
_INFO_REQUEST_RE = re.compile("|".join(_INFO_REQUEST_PATTERNS), re.IGNORECASE)


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


def has_helpdesk_ui_block(text: str) -> bool:
    return bool(_UI_BLOCK.search(text or ""))


def looks_like_info_request_without_widget(text: str) -> bool:
    """Detecta cuando el LLM pide datos al usuario PERO no emitió un bloque helpdesk-ui."""
    if not text:
        return False
    if has_helpdesk_ui_block(text):
        return False
    return bool(_INFO_REQUEST_RE.search(text))


_GENERIC_SURVEY_JSON = json.dumps({
    "survey": {
        "id": "diag_generic",
        "prompt": "Para afinar el diagnóstico, completa estos datos:",
        "fields": [
            {"id": "equipo", "label": "Marca y modelo del equipo/dispositivo", "type": "text", "placeholder": "Ej. MacBook Pro M2 / HP LaserJet Pro"},
            {"id": "os", "label": "Sistema operativo", "type": "choice", "options": ["Windows 10", "Windows 11", "macOS", "Otro"]},
            {"id": "cuando", "label": "¿Desde cuándo ocurre?", "type": "choice", "options": ["Hoy", "Esta semana", "Hace más tiempo"]},
            {"id": "detalle", "label": "Detalles adicionales o mensaje de error visible", "type": "textarea", "placeholder": "Texto exacto del error si lo hay, o 'ninguno'"},
        ],
    }
}, ensure_ascii=False)


def ensure_widget_if_info_request(text: str) -> str:
    """Si el LLM pide datos pero olvidó el widget, le inyectamos un survey genérico.

    Esto evita el caso en que el asistente referencia 'el formulario' sin haberlo emitido.
    """
    if not looks_like_info_request_without_widget(text):
        return text
    fallback = "\n\n```helpdesk-ui\n" + _GENERIC_SURVEY_JSON + "\n```\n"
    return (text or "").rstrip() + fallback
