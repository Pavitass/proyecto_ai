"""Análisis de capturas (visión): Gemini o API compatible con OpenAI (GPT-4o, OpenRouter, etc.).

El grafo del agente sigue usando el LLM de chat configurado (p. ej. DeepSeek solo texto).
"""

from __future__ import annotations

import base64
import binascii

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from helpdesk_app.config import (
    GOOGLE_API_KEY,
    HELPDESK_VISION_OPENAI_API_KEY,
    HELPDESK_VISION_OPENAI_BASE_URL,
    HELPDESK_VISION_OPENAI_MODEL,
    LLM_TEMPERATURE,
    VISION_MODEL,
    resolve_vision_backend,
)

_MAX_BYTES = 1_400_000
_MAX_IMAGES = 2

_VISION_SYSTEM = """Eres un técnico de mesa de ayuda TI observando capturas de pantalla del usuario.
Describe con precisión y en español:
- Qué aplicación o ventana parece ser (título de ventana, barra de tareas, iconos reconocibles).
- Textos de error o avisos que puedas leer (copia literal si es corto).
- Botones o campos relevantes (Siguiente, Conectar, Aceptar, etc.).
- Si algo es ilegible o dudoso, dilo explícitamente.
No inventes texto que no veas. Usa viñetas y bloques cortos. Máximo ~700 palabras."""


def _strip_data_url(b64_or_data_url: str) -> str:
    s = (b64_or_data_url or "").strip()
    if "," in s and s.lower().startswith("data:"):
        return s.split(",", 1)[1].strip()
    return s


def _mime_for_image_bytes(data: bytes) -> str:
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"


def _build_multimodal_parts(user_message: str, images_b64: list[str]) -> list:
    imgs = [_strip_data_url(x) for x in images_b64[:_MAX_IMAGES]]
    user_text = (user_message or "").strip()[:4000] or "(El usuario solo envió capturas.)"
    parts: list = [
        {
            "type": "text",
            "text": (
                "Contexto del usuario:\n"
                + user_text
                + "\n\nDescribe todo lo relevante que observes en las imágenes adjuntas, "
                "en orden si hay varias."
            ),
        }
    ]
    for raw in imgs:
        try:
            data = base64.b64decode(raw, validate=False)
        except binascii.Error as e:
            raise ValueError("Imagen base64 inválida.") from e
        if len(data) > _MAX_BYTES:
            raise ValueError(
                f"Cada imagen debe pesar menos de ~{_MAX_BYTES // 1_000_000} MB tras decodificar."
            )
        mime = _mime_for_image_bytes(data)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{raw}"},
            }
        )
    return parts


def _content_to_str(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(block.get("text", ""))
            elif isinstance(block, str):
                out.append(block)
        return "\n".join(out).strip()
    return str(content).strip()


def _describe_google(user_message: str, images_b64: list[str]) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "Visión con Gemini requiere GOOGLE_API_KEY en .env, "
            "o configura HELPDESK_VISION_BACKEND=openai con OPENAI_API_KEY (u otra API compatible)."
        )
    parts = _build_multimodal_parts(user_message, images_b64)
    llm = ChatGoogleGenerativeAI(
        model=VISION_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=min(LLM_TEMPERATURE, 0.3),
    )
    msg = llm.invoke(
        [
            SystemMessage(content=_VISION_SYSTEM),
            HumanMessage(content=parts),
        ]
    )
    return _content_to_str(msg.content)


def _describe_openai_compatible(user_message: str, images_b64: list[str]) -> str:
    if not HELPDESK_VISION_OPENAI_API_KEY:
        raise RuntimeError(
            "Visión con API compatible OpenAI requiere HELPDESK_VISION_OPENAI_API_KEY "
            "o OPENAI_API_KEY. Opcional: HELPDESK_VISION_OPENAI_BASE_URL y "
            "HELPDESK_VISION_OPENAI_MODEL (p. ej. gpt-4o-mini)."
        )
    parts = _build_multimodal_parts(user_message, images_b64)
    llm = ChatOpenAI(
        model=HELPDESK_VISION_OPENAI_MODEL,
        api_key=HELPDESK_VISION_OPENAI_API_KEY,
        base_url=HELPDESK_VISION_OPENAI_BASE_URL,
        temperature=min(LLM_TEMPERATURE, 0.3),
    )
    msg = llm.invoke(
        [
            SystemMessage(content=_VISION_SYSTEM),
            HumanMessage(content=parts),
        ]
    )
    return _content_to_str(msg.content)


def describe_screenshots(user_message: str, images_b64: list[str]) -> str:
    if not images_b64:
        raise ValueError("No se recibieron imágenes.")
    backend = resolve_vision_backend()
    if backend == "google":
        return _describe_google(user_message, images_b64)
    if backend == "openai":
        return _describe_openai_compatible(user_message, images_b64)
    raise RuntimeError(
        "No hay proveedor de visión configurado. Por defecto se usa **Google (Gemini)**:\n"
        "• Añade GOOGLE_API_KEY en .env (Google AI Studio).\n"
        "• Opcional: HELPDESK_VISION_MODEL=gemini-2.0-flash\n"
        "Si prefieres OpenAI u otro compatible: HELPDESK_VISION_BACKEND=openai y "
        "HELPDESK_VISION_OPENAI_API_KEY (u OPENAI_API_KEY).\n"
        "Nota: el modelo de chat DeepSeek habitual no analiza imágenes; la visión va por Gemini salvo que fuerces openai."
    )
