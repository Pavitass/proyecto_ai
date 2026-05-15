import pytest
from helpdesk_app import agent_trace


@pytest.fixture(autouse=True)
def _reset():
    agent_trace._RUNS.clear()
    yield
    agent_trace._RUNS.clear()


def test_begin_turn_creates_run():
    run = agent_trace.begin_turn("thr-1", "turn-a")
    assert run.turn_id == "turn-a"
    assert run.finished is False
    assert agent_trace.get_run("turn-a") is run


def test_emit_adds_to_history_and_queue():
    run = agent_trace.begin_turn("thr-1", "turn-b")
    agent_trace.emit("turn-b", "tool_start", {"name": "x", "args_preview": "y"})
    assert len(run.events_history) == 1
    assert run.events_history[0]["type"] == "tool_start"
    got = run.event_queue.get_nowait()
    assert got["type"] == "tool_start"


def test_end_turn_marks_finished_and_emits_done():
    run = agent_trace.begin_turn("thr-1", "turn-c")
    agent_trace.end_turn("turn-c")
    assert run.finished is True
    types = [e["type"] for e in run.events_history]
    assert "phase" in types
    assert any(e.get("phase") == "done" for e in run.events_history if e["type"] == "phase")


def test_emit_truncates_after_max_events():
    agent_trace.begin_turn("thr-1", "turn-d")
    for i in range(agent_trace._MAX_EVENTS_PER_RUN + 20):
        agent_trace.emit("turn-d", "tool_start", {"name": f"n{i}", "args_preview": ""})
    run = agent_trace.get_run("turn-d")
    assert len(run.events_history) == agent_trace._MAX_EVENTS_PER_RUN


def test_get_or_create_run_creates_lazy():
    run = agent_trace.get_or_create_run("thr-2", "turn-lazy")
    assert run.turn_id == "turn-lazy"
    assert agent_trace.get_run("turn-lazy") is run


def test_cleanup_old_runs_removes_old_finished():
    import time
    run = agent_trace.begin_turn("thr-1", "turn-old")
    agent_trace.end_turn("turn-old")
    run.started_at = time.time() - 1000
    agent_trace.cleanup_old_runs(max_age_s=10)
    assert agent_trace.get_run("turn-old") is None
