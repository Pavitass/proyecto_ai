"""Plan de automatización de escritorio (JSON) generado por el LLM. Solo acciones acotadas."""

from __future__ import annotations

import json
import platform
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from helpdesk_app.llm import get_chat_model

_MAX_ACTIONS = 22

_ALLOWED_HOTKEY_KEYS = frozenset(
    {
        "LeftCmd",
        "LeftSuper",
        "LeftWin",
        "RightWin",
        "Space",
        "Return",
        "Enter",
        "Tab",
        "Escape",
        "Up",
        "Down",
        "Left",
        "Right",
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "I",
        "J",
        "K",
        "L",
        "M",
        "N",
        "O",
        "P",
        "Q",
        "R",
        "S",
        "T",
        "U",
        "V",
        "W",
        "X",
        "Y",
        "Z",
    }
)


_SYSTEM = (
    "Eres un planificador de automatización de escritorio.\n"
    "El usuario describe un objetivo. Responde con un ÚNICO objeto JSON válido "
    "(sin markdown, sin ```, sin texto antes ni después):\n"
    '{"rationale":"1-4 frases en español","actions":[...]}\n\n'
    "Acciones permitidas (cada una con \"type\"):\n"
    '- {"type":"hotkey","keys":["LeftCmd","Space"],"delayMs":400} — pulsa combinación: '
    "primero modificadores en orden, última tecla es la principal. En macOS usa LeftCmd para ⌘; "
    "en Windows usa LeftWin para ⊞ o LeftSuper según convenga.\n"
    '- {"type":"move","x":0.0,"y":0.0,"delayMs":200} — x,y fracción 0..1 de la pantalla principal.\n'
    '- {"type":"click","button":"left","delayMs":150}\n'
    '- {"type":"wait","delayMs":800}\n'
    '- {"type":"type","text":"texto","delayMs":120} — máximo 120 caracteres; puede incluir saltos con \\n.\n'
    '- Cada acción puede llevar **"sensitive": true** si es delicada (ajustes del sistema, borrados, '
    "privacidad, seguridad, clic que podría confirmar algo irreversible). Pasos normales de navegación: "
    '"sensitive": false (omítelo).\n\n'
    "Consejos por objetivo:\n"
    "- Abrir Spotlight (macOS): hotkey LeftCmd+Space, wait, type texto de búsqueda, hotkey Return.\n"
    "- Abrir menú Inicio / búsqueda (Windows): LeftWin, wait, type, Return.\n"
    "- **Ahorro de batería / Low Power Mode (macOS)**: preferir Spotlight: hotkey LeftCmd+Space; "
    "type \"Ahorro de batería\" o \"Battery\" o \"Batería\" según idioma del sistema; Return; "
    "luego wait y move/click hacia zona del interruptor (aprox. centro-derecha de la ventana; "
    "ajusta x,y si el usuario envió captura de pantalla).\n"
    "- **Ahorro de batería (Windows)**: LeftWin, type \"Uso de batería\" o \"Battery saver\", Return; "
    "luego clicks en interruptores visibles (coordenadas con captura ayudan mucho).\n"
    "- Marca **sensitive: true** en clics que activen interruptores del sistema, envíos que confirmen "
    "diálogos, o cualquier paso que el usuario deba revisar antes.\n\n"
    "Si el usuario adjunta descripción de **captura de pantalla**, usa coordenadas más fiables.\n"
    f"Máximo {_MAX_ACTIONS} acciones.\n"
    "Si el objetivo es peligroso o requiere contraseña administrativa que no se puede automatizar, "
    'usa "actions": [] y explica en rationale.\n'
)


class DesktopAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["move", "click", "wait", "type", "hotkey"]
    x: float | None = None
    y: float | None = None
    button: Literal["left", "right"] = "left"
    delayMs: int = Field(default=200, ge=0, le=30_000)
    text: str | None = None
    keys: list[str] = Field(default_factory=list, max_length=4)
    sensitive: bool = False

    @model_validator(mode="after")
    def validate_by_type(self):
        t = self.type
        if t == "move":
            if self.x is None or self.y is None:
                raise ValueError("move requiere x e y")
            if not (0 <= self.x <= 1 and 0 <= self.y <= 1):
                raise ValueError("x e y deben estar entre 0 y 1")
        if t == "type":
            tx = (self.text or "").strip()
            if not tx:
                raise ValueError("type requiere text")
            if len(tx) > 120:
                raise ValueError("text demasiado largo")
        if t == "wait" and self.delayMs < 1:
            raise ValueError("wait requiere delayMs >= 1")
        if t == "hotkey":
            if not self.keys:
                raise ValueError("hotkey requiere keys")
            for k in self.keys:
                if k not in _ALLOWED_HOTKEY_KEYS:
                    raise ValueError(f"Tecla no permitida en hotkey: {k}")
        return self


class DesktopPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rationale: str = ""
    actions: list[DesktopAction] = Field(default_factory=list, max_length=_MAX_ACTIONS)


class DesktopPlanError(Exception):
    pass


def _extract_json(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        raise DesktopPlanError("Respuesta vacía del modelo.")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise DesktopPlanError("El modelo no devolvió JSON válido.") from e


def generate_desktop_plan(
    goal: str,
    screenshot_b64: list[str] | None = None,
    client_os: str | None = None,
) -> dict[str, Any]:
    goal = (goal or "").strip()
    if len(goal) < 4:
        raise DesktopPlanError("Describe el objetivo con al menos unas pocas palabras.")
    if len(goal) > 2000:
        raise DesktopPlanError("Objetivo demasiado largo.")

    extra = ""
    shots = [x for x in (screenshot_b64 or []) if x][:1]
    if shots:
        from helpdesk_app import vision

        try:
            summary = vision.describe_screenshots(goal, shots)
            extra = "\n\n### Lo visible en la captura de pantalla del usuario\n\n" + summary
        except Exception as e:
            raise DesktopPlanError("No se pudo analizar la captura: " + str(e)) from e

    co = (client_os or "").strip().lower() or None
    if co == "darwin":
        os_hint = "macOS (cliente Electron)"
    elif co == "win32":
        os_hint = "Windows (cliente Electron)"
    elif co == "linux":
        os_hint = "Linux (cliente Electron)"
    else:
        os_hint = f"{platform.system()} (servidor; si el cliente es otro, el plan puede no coincidir)"

    system_full = _SYSTEM + f"\n\n**Importante:** asume que el escritorio donde se ejecutará el plan es: **{os_hint}**.\n"

    model = get_chat_model()
    msg = model.invoke(
        [
            SystemMessage(content=system_full),
            HumanMessage(content="Objetivo del usuario:\n" + goal + extra),
        ]
    )
    raw = msg.content
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        raw = "\n".join(parts)
    if not isinstance(raw, str):
        raw = str(raw)

    data = _extract_json(raw)
    try:
        plan = DesktopPlan.model_validate(data)
    except Exception as e:
        raise DesktopPlanError(f"Plan inválido: {e}") from e
    return {"rationale": plan.rationale.strip(), "actions": [a.model_dump() for a in plan.actions]}
