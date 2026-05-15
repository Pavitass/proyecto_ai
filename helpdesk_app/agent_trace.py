"""Eventos en vivo de la actividad del agente, por turno."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_MAX_EVENTS_PER_RUN = 200


@dataclass
class TraceRun:
    turn_id: str
    thread_id: str
    started_at: float = field(default_factory=time.time)
    finished: bool = False
    event_queue: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    events_history: list[dict] = field(default_factory=list)


_RUNS: dict[str, TraceRun] = {}
_LOCK = threading.Lock()


def begin_turn(thread_id: str, turn_id: str) -> TraceRun:
    with _LOCK:
        run = _RUNS.get(turn_id)
        if run is None:
            run = TraceRun(turn_id=turn_id, thread_id=thread_id)
            _RUNS[turn_id] = run
        else:
            # Lazy run was created by an early SSE connection — populate thread_id now.
            run.thread_id = thread_id or run.thread_id
            run.started_at = time.time()
    return run


def get_run(turn_id: str) -> TraceRun | None:
    with _LOCK:
        return _RUNS.get(turn_id)


def get_or_create_run(thread_id: str, turn_id: str) -> TraceRun:
    with _LOCK:
        run = _RUNS.get(turn_id)
        if run is None:
            run = TraceRun(turn_id=turn_id, thread_id=thread_id)
            _RUNS[turn_id] = run
    return run


def emit(turn_id: str, type_: str, payload: dict) -> None:
    run = get_run(turn_id)
    if run is None:
        return
    ev = {"type": type_, "ts": time.time(), **payload}
    with _LOCK:
        run.events_history.append(ev)
        if len(run.events_history) > _MAX_EVENTS_PER_RUN:
            del run.events_history[0:len(run.events_history) - _MAX_EVENTS_PER_RUN]
    run.event_queue.put(ev)


def end_turn(turn_id: str) -> None:
    run = get_run(turn_id)
    if run is None:
        return
    emit(turn_id, "phase", {"phase": "done"})
    with _LOCK:
        run.finished = True


def cleanup_old_runs(max_age_s: float = 600.0) -> None:
    cutoff = time.time() - max_age_s
    with _LOCK:
        stale = [k for k, v in _RUNS.items() if v.finished and v.started_at < cutoff]
        for k in stale:
            _RUNS.pop(k, None)


def emit_by_thread(thread_id: str, type_: str, payload: dict) -> None:
    """Helper for code paths that only know thread_id — find the most recent active run."""
    with _LOCK:
        active = [r for r in _RUNS.values() if r.thread_id == thread_id and not r.finished]
        if not active:
            return
        run = max(active, key=lambda r: r.started_at)
    emit(run.turn_id, type_, payload)
