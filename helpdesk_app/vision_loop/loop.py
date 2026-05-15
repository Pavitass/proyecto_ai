"""Loop visual agéntico: state machine."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from helpdesk_app.config import BASE_DIR, desktop_py_exec_enabled
from helpdesk_app.vision_loop import events as ev
from helpdesk_app.vision_loop.actor import HistoryItem, next_action as real_next_action
from helpdesk_app.vision_loop.executor import ExecutionError, run as real_execute
from helpdesk_app.vision_loop.schema import LoopDecision
from helpdesk_app.vision_loop.screen import Capture, capture as real_capture


@dataclass
class LoopOutcome:
    status: str
    reason: str = ""
    steps: int = 0
    final_screenshot_b64: str = ""    # captura PNG (b64) del estado final, útil para análisis


_AUDIT_PATH = Path(BASE_DIR) / "data" / "automation_log.jsonl"


def _auto_hide_enabled() -> bool:
    import os
    return os.getenv("HELPDESK_AUTO_HIDE_ON_LOOP", "1").strip().lower() not in ("0", "false", "no", "off")


# Estado por run: guardamos el título de la ventana que ocultamos para restaurarla después.
_HIDDEN_WINDOW_TITLE: dict[str, str] = {}


def _auto_hide_foreground_window(state, sleep_fn) -> None:
    """Oculta la ventana en primer plano (presumiblemente la app helpdesk) al inicio
    del loop, para que no aparezca en las capturas y confunda al actor de visión.

    En Windows, guarda el título de la ventana para restaurarla por nombre al final.
    En macOS, usa Cmd+H (clásico).
    Se puede desactivar con HELPDESK_AUTO_HIDE_ON_LOOP=0."""
    import sys
    if not _auto_hide_enabled():
        return
    try:
        import pyautogui
        if sys.platform == "darwin":
            pyautogui.hotkey("command", "h")
            sleep_fn(0.6)
        elif sys.platform.startswith("win"):
            # Captura el título de la ventana activa ANTES de minimizar
            try:
                import pygetwindow as gw
                active = gw.getActiveWindow()
                if active and active.title:
                    _HIDDEN_WINDOW_TITLE[state.run_id] = active.title
            except Exception:
                pass
            pyautogui.hotkey("win", "down")
            sleep_fn(0.6)
        else:
            try:
                pyautogui.hotkey("winleft", "h")
                sleep_fn(0.6)
            except Exception:
                pass
    except Exception:
        pass


def _auto_restore_helpdesk_window(state, sleep_fn) -> None:
    """Trae de vuelta la app helpdesk al terminar el loop, para que el usuario siga viendo
    el resultado (resumen, panel de trace, ticket, etc.).

    En Windows, restauramos por título exacto (más fiable que Alt+Tab).
    En macOS, Cmd+Tab (la app oculta vuelve al foco).
    """
    import sys
    if not _auto_hide_enabled():
        return
    try:
        import pyautogui
        if sys.platform == "darwin":
            pyautogui.hotkey("command", "tab")
            sleep_fn(0.4)
        elif sys.platform.startswith("win"):
            title = _HIDDEN_WINDOW_TITLE.pop(state.run_id, "")
            restored = False
            if title:
                try:
                    import pygetwindow as gw
                    matches = gw.getWindowsWithTitle(title)
                    if matches:
                        w = matches[0]
                        # Restaurar desde minimizado y activar
                        try:
                            if w.isMinimized:
                                w.restore()
                            w.activate()
                            restored = True
                        except Exception:
                            pass
                except Exception:
                    pass
            if not restored:
                # Fallback: Alt+Tab estándar
                pyautogui.hotkey("alt", "tab")
            sleep_fn(0.4)
            # Flash de la barra de tareas como feedback adicional (parpadea el icono)
            _flash_taskbar_windows(title)
        else:
            try:
                pyautogui.hotkey("alt", "tab")
                sleep_fn(0.4)
            except Exception:
                pass
    except Exception:
        pass


def _flash_taskbar_windows(title: str) -> None:
    """En Windows, hace parpadear el icono de la app en la barra de tareas para llamar
    la atención del usuario. Usa la API nativa FlashWindowEx vía ctypes."""
    import sys
    if not sys.platform.startswith("win") or not title:
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # FindWindow por título
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return

        # FLASHWINFO struct
        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        FLASHW_ALL = 0x00000003
        FLASHW_TIMERNOFG = 0x0000000C
        fwi = FLASHWINFO(
            cbSize=ctypes.sizeof(FLASHWINFO),
            hwnd=hwnd,
            dwFlags=FLASHW_ALL | FLASHW_TIMERNOFG,
            uCount=5,
            dwTimeout=0,
        )
        user32.FlashWindowEx(ctypes.byref(fwi))
    except Exception:
        pass


def _audit(run_id: str, payload: dict) -> None:
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": run_id, "ts": time.time(), **payload}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _summarize_action(d: LoopDecision) -> str:
    if d.action is None:
        return "(terminal)"
    a = d.action
    if a.type == "hotkey":
        return "hotkey " + "+".join(a.keys)
    if a.type == "move":
        return f"move {a.x:.2f},{a.y:.2f}"
    if a.type == "click":
        return f"click {a.button}"
    if a.type == "type":
        txt = (a.text or "")[:24]
        return f"type {txt!r}"
    if a.type == "wait":
        return f"wait {a.delayMs}ms"
    return a.type


def run_loop(
    state: ev.RunState,
    *,
    max_steps: int = 20,
    total_timeout_s: float = 90.0,
    capture_fn: Callable[[], Capture] = real_capture,
    actor_fn: Callable[..., LoopDecision] = real_next_action,
    execute_fn: Callable[..., None] = real_execute,
    sleep_fn: Callable[[float], None] = time.sleep,
    confirm_fn: Callable[[ev.RunState, dict], bool] = ev.request_confirm,
) -> LoopOutcome:
    if not desktop_py_exec_enabled():
        outcome = LoopOutcome(status="gate_disabled", reason="HELPDESK_DESKTOP_PY_EXEC no está activo")
        ev.emit(state, "fail", {"reason": outcome.reason})
        ev.finish_run(state.run_id)
        return outcome

    # Auto-hide la app helpdesk al inicio para que no aparezca en las capturas
    # (evita el bucle recursivo donde el actor confunde nuestra propia UI con el SO).
    _auto_hide_foreground_window(state, sleep_fn)

    history: list[HistoryItem] = []
    t0 = time.time()
    step_n = 0
    try:
        for step_n in range(1, max_steps + 1):
            if state.abort_flag.is_set():
                outcome = LoopOutcome(status="aborted", reason="user_abort", steps=step_n - 1)
                ev.emit(state, "aborted", {"reason": outcome.reason})
                return outcome
            if time.time() - t0 > total_timeout_s:
                outcome = LoopOutcome(status="timeout", steps=step_n - 1)
                ev.emit(state, "fail", {"reason": "timeout"})
                return outcome

            cap = capture_fn()
            try:
                decision = actor_fn(state.goal, cap.png_b64, history)
            except Exception as e:
                outcome = LoopOutcome(status="fail", reason=f"actor_error: {e}", steps=step_n - 1)
                ev.emit(state, "fail", {"reason": outcome.reason})
                _audit(state.run_id, {"event": "actor_error", "error": str(e)})
                return outcome

            summary = _summarize_action(decision)
            ev.emit(state, "step", {
                "n": step_n,
                "max": max_steps,
                "thumb_b64": cap.thumb_b64,
                "reasoning": decision.reasoning,
                "action": decision.action.model_dump() if decision.action else None,
                "summary": summary,
                "sensitive": bool(decision.action and decision.action.sensitive),
            })
            _audit(state.run_id, {"event": "step", "n": step_n, "summary": summary,
                                  "reasoning": decision.reasoning,
                                  "action": decision.action.model_dump() if decision.action else None})

            if decision.done:
                ev.emit(state, "done", {"reason": decision.reason or "objetivo cumplido"})
                return LoopOutcome(status="done", reason=decision.reason, steps=step_n, final_screenshot_b64=cap.png_b64)
            if decision.fail:
                ev.emit(state, "fail", {"reason": decision.reason or "actor:fail"})
                return LoopOutcome(status="fail", reason=decision.reason, steps=step_n, final_screenshot_b64=cap.png_b64)
            if decision.needs_user:
                ev.emit(state, "needs_user", {"reason": decision.reason or "se requiere usuario"})
                return LoopOutcome(status="needs_user", reason=decision.reason, steps=step_n, final_screenshot_b64=cap.png_b64)

            if decision.action and decision.action.sensitive:
                approved = confirm_fn(state, {
                    "n": step_n,
                    "full_b64": cap.png_b64,
                    "summary": summary,
                    "reasoning": decision.reasoning,
                    "action": decision.action.model_dump(),
                })
                if not approved:
                    outcome = LoopOutcome(status="user_canceled", reason="rechazada por usuario", steps=step_n)
                    ev.emit(state, "aborted", {"reason": outcome.reason})
                    return outcome

            try:
                execute_fn(decision.action)
            except ExecutionError as e:
                outcome = LoopOutcome(status="fail", reason=f"exec_error: {e}", steps=step_n)
                ev.emit(state, "fail", {"reason": outcome.reason})
                _audit(state.run_id, {"event": "exec_error", "error": str(e)})
                return outcome

            history.append(HistoryItem(reasoning=decision.reasoning, action_summary=summary))
            sleep_fn(0.05)

        outcome = LoopOutcome(status="max_steps", steps=max_steps)
        ev.emit(state, "fail", {"reason": "max_steps"})
        return outcome
    finally:
        ev.finish_run(state.run_id)
        # Trae de vuelta la app helpdesk para que el usuario siga viendo el resultado
        _auto_restore_helpdesk_window(state, sleep_fn)
