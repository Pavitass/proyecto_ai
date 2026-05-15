"""LLM con visión (Gemini) — emite UNA acción por turno."""
from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from helpdesk_app.config import GOOGLE_API_KEY, VISION_MODEL
from helpdesk_app.vision_loop.schema import LoopDecision


_SYSTEM = (
    "Eres un agente que controla un escritorio paso a paso. Mira la captura actual, "
    "el objetivo y el historial; decide UNA sola acción atómica que avance hacia el objetivo. "
    "Responde con un objeto JSON ESTRICTO (sin markdown, sin ```), con esta forma:\n"
    '{"reasoning": "1-3 frases en español",\n'
    ' "action": {"type":"hotkey|move|click|type|wait", ...campos..., "sensitive": false},\n'
    ' "done": false, "fail": false, "needs_user": false, "reason": ""}\n\n'
    "Reglas:\n"
    "- Si el objetivo ya se cumplió en la captura, devuelve done:true y action:null.\n"
    "- Si no puedes avanzar sin el usuario (contraseña, captcha, ambigüedad), needs_user:true y reason.\n"
    "- Si es imposible o peligroso, fail:true y reason.\n"
    "- NUNCA escribas contraseñas. Si la UI las pide, needs_user:true.\n"
    "- Marca sensitive:true en envíos de correos, borrados, ajustes del sistema.\n"
    "- Acciones permitidas (mismo schema que el resto del sistema):\n"
    '  * {"type":"hotkey","keys":["LeftCmd","Space"],"delayMs":400}\n'
    '  * {"type":"move","x":0.5,"y":0.5,"delayMs":200}  (x,y en fracción 0..1)\n'
    '  * {"type":"click","button":"left","delayMs":150}\n'
    '  * {"type":"type","text":"texto","delayMs":120}\n'
    '  * {"type":"wait","delayMs":800}\n'
    "- Las coordenadas (x,y) deben mirar a la imagen real. No inventes coordenadas si el target no está visible.\n"
    "- Una sola acción por respuesta. Nada de listas.\n"
)


@dataclass
class HistoryItem:
    reasoning: str
    action_summary: str


def _make_vision_model():
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "El loop visual requiere GOOGLE_API_KEY (Gemini). "
            "Configura la variable en .env o exporta antes de arrancar."
        )
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=VISION_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=0.1,
        max_output_tokens=1024,
        model_kwargs={"response_mime_type": "application/json"},
    )


def _strip_json(raw: str) -> str:
    s = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    if fence:
        s = fence.group(1).strip()
    return s


def _format_history(history: list[HistoryItem]) -> str:
    if not history:
        return "(sin historial)"
    return "\n".join(
        f"{i+1}. {h.action_summary} — {h.reasoning}" for i, h in enumerate(history[-4:])
    )


def next_action(
    goal: str,
    screenshot_png_b64: str,
    history: list[HistoryItem],
    os_hint: str | None = None,
) -> LoopDecision:
    model = _make_vision_model()
    os_hint = os_hint or platform.system()
    user_text = (
        f"Objetivo: {goal}\n"
        f"Sistema operativo: {os_hint}\n"
        f"Historial reciente:\n{_format_history(history)}\n"
        "Responde solo con el JSON descrito en las reglas."
    )
    msg = model.invoke(
        [
            SystemMessage(content=_SYSTEM),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": f"data:image/png;base64,{screenshot_png_b64}",
                    },
                ]
            ),
        ]
    )
    raw = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
    cleaned = _strip_json(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Actor returned non-JSON: {e}: {cleaned[:200]}") from e
    return LoopDecision.model_validate(data)
