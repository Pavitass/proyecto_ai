"""Ejecuta una DesktopAction usando el runner PyAutoGUI existente."""
from __future__ import annotations

from helpdesk_app.desktop_exec_py import run_pyautogui_action
from helpdesk_app.desktop_plan import DesktopAction


class ExecutionError(RuntimeError):
    pass


def run(action: DesktopAction) -> None:
    payload = action.model_dump()
    err = run_pyautogui_action(payload)
    if err:
        raise ExecutionError(err)
