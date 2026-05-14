"""Registro de runs activos + cola de eventos para SSE y confirmaciones humanas."""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunState:
    run_id: str
    goal: str
    started_at: float = field(default_factory=time.time)
    abort_flag: threading.Event = field(default_factory=threading.Event)
    confirm_queue: "queue.Queue[bool]" = field(default_factory=queue.Queue)
    event_queue: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    finished: bool = False


_RUNS: dict[str, RunState] = {}
_LOCK = threading.Lock()


def create_run(goal: str) -> RunState:
    rid = uuid.uuid4().hex[:12]
    state = RunState(run_id=rid, goal=goal)
    with _LOCK:
        _RUNS[rid] = state
    return state


def get_run(run_id: str) -> RunState | None:
    with _LOCK:
        return _RUNS.get(run_id)


def finish_run(run_id: str) -> None:
    with _LOCK:
        st = _RUNS.get(run_id)
        if st:
            st.finished = True


def cleanup_old_runs(max_age_s: float = 600.0) -> None:
    cutoff = time.time() - max_age_s
    with _LOCK:
        stale = [k for k, v in _RUNS.items() if v.finished and v.started_at < cutoff]
        for k in stale:
            _RUNS.pop(k, None)


def emit(state: RunState, event_type: str, payload: dict) -> None:
    state.event_queue.put({"type": event_type, "ts": time.time(), **payload})


def request_confirm(state: RunState, payload: dict, timeout_s: float = 60.0) -> bool:
    """Block until UI POSTs a confirmation or timeout."""
    emit(state, "confirm_required", payload)
    try:
        return state.confirm_queue.get(timeout=timeout_s)
    except queue.Empty:
        return False
