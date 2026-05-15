"""Contexto por petición (p. ej. SO del cliente) legible desde herramientas del grafo."""

from __future__ import annotations

from contextvars import ContextVar

chat_client_os: ContextVar[str | None] = ContextVar("chat_client_os", default=None)
chat_thread_id: ContextVar[str] = ContextVar("chat_thread_id", default="")
