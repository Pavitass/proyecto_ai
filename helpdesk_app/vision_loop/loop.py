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


_AUDIT_PATH = Path(BASE_DIR) / "data" / "automation_log.jsonl"


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
                return LoopOutcome(status="done", reason=decision.reason, steps=step_n)
            if decision.fail:
                ev.emit(state, "fail", {"reason": decision.reason or "actor:fail"})
                return LoopOutcome(status="fail", reason=decision.reason, steps=step_n)
            if decision.needs_user:
                ev.emit(state, "needs_user", {"reason": decision.reason or "se requiere usuario"})
                return LoopOutcome(status="needs_user", reason=decision.reason, steps=step_n)

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
