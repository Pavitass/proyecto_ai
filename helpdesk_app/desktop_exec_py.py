"""Ejecuta una acción de plan de escritorio con PyAutoGUI (misma máquina que el proceso uvicorn)."""

from __future__ import annotations

import sys
import time
from typing import Any

_ARROW_PG = {"Up": "up", "Down": "down", "Left": "left", "Right": "right"}


def _pg_key_token(name: str) -> str:
    """Convierte nombres del plan (nut-tree) a teclas de PyAutoGUI."""
    n = str(name).strip()
    mac = sys.platform == "darwin"
    win = sys.platform.startswith("win")

    if n in ("LeftCmd", "LeftSuper"):
        return "command" if mac else "win"
    if n in ("LeftWin", "RightWin"):
        return "win" if (win or not mac) else "command"
    if n == "Space":
        return "space"
    if n in ("Return", "Enter"):
        return "return" if mac else "enter"
    if n == "Tab":
        return "tab"
    if n == "Escape":
        return "esc"
    if n in _ARROW_PG:
        return _ARROW_PG[n]
    if len(n) == 1 and n.isalpha():
        return n.lower()
    raise ValueError(f"Tecla no soportada en PyAutoGUI: {n}")


def run_pyautogui_action(action: dict[str, Any]) -> str | None:
    """
    Ejecuta una acción. Devuelve None si OK, o mensaje de error en texto.
    Requiere que el paquete pyautogui esté instalado.
    """
    try:
        import pyautogui
    except ImportError:
        return "Falta el paquete pyautogui (pip install pyautogui)."

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.04

    t = action.get("type")
    if t not in ("move", "click", "wait", "type", "hotkey"):
        return "Tipo de acción no permitido"

    delay_ms = min(max(int(action.get("delayMs") or 200), 0), 5000)

    try:
        if t == "wait":
            ms = min(max(int(action.get("delayMs") or 0), 1), 15000)
            time.sleep(ms / 1000.0)
            return None

        if t == "move":
            w, h = pyautogui.size()
            x = int(float(action["x"]) * w)
            y = int(float(action["y"]) * h)
            pyautogui.moveTo(x, y, duration=0.12)
            time.sleep(delay_ms / 1000.0)
            return None

        if t == "click":
            btn = action.get("button") or "left"
            pyautogui.click(button=btn)
            time.sleep(delay_ms / 1000.0)
            return None

        if t == "type":
            raw = str(action.get("text") or "").replace("\\n", "\n")
            if any(ord(ch) > 127 for ch in raw):
                try:
                    import pyperclip
                except ImportError:
                    return (
                        "El texto contiene caracteres no ASCII (p. ej. acentos). "
                        "Instala pyperclip (`pip install pyperclip`) para pegar desde el portapapeles."
                    )
                try:
                    pyperclip.copy(raw)
                    time.sleep(0.08)
                    if sys.platform == "darwin":
                        pyautogui.hotkey("command", "v")
                    else:
                        pyautogui.hotkey("ctrl", "v")
                except Exception as e:
                    return f"No se pudo pegar texto Unicode: {e}"
                time.sleep(delay_ms / 1000.0)
                return None
            lines = raw.split("\n")
            for i, line in enumerate(lines):
                if line:
                    pyautogui.write(line, interval=0.02)
                if i < len(lines) - 1:
                    pyautogui.press("enter")
            time.sleep(delay_ms / 1000.0)
            return None

        if t == "hotkey":
            names = action.get("keys") or []
            if not isinstance(names, list) or not names:
                return "hotkey sin teclas"
            keys = [_pg_key_token(str(x)) for x in names]
            pyautogui.hotkey(*keys)
            time.sleep(delay_ms / 1000.0)
            return None
    except ValueError as e:
        return str(e)
    except Exception as e:
        return e.args[0] if e.args else str(e)

    return "Tipo desconocido"
