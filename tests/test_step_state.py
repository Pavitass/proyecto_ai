import pytest
from helpdesk_app import step_state


@pytest.fixture(autouse=True)
def _reset():
    step_state.clear_all()
    yield
    step_state.clear_all()


def test_upsert_then_get():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "abrir spotlight"}, {"index": 1, "text": "escribir"}])
    got = step_state.get_steps("t1")
    assert got == {"m1": [{"index": 0, "text": "abrir spotlight", "status": "pending", "note": ""},
                          {"index": 1, "text": "escribir", "status": "pending", "note": ""}]}


def test_update_step_status():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "abrir spotlight"}])
    ok = step_state.update_step("t1", "m1", 0, "done")
    assert ok is True
    got = step_state.get_steps("t1")
    assert got["m1"][0]["status"] == "done"


def test_update_stuck_carries_note():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "x"}])
    ok = step_state.update_step("t1", "m1", 0, "stuck", note="no aparece el botón")
    assert ok is True
    assert step_state.get_steps("t1")["m1"][0] == {"index": 0, "text": "x", "status": "stuck", "note": "no aparece el botón"}


def test_update_unknown_thread_returns_false():
    assert step_state.update_step("nope", "m1", 0, "done") is False


def test_update_unknown_index_returns_false():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "x"}])
    assert step_state.update_step("t1", "m1", 5, "done") is False


def test_update_invalid_status_raises():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "x"}])
    with pytest.raises(ValueError):
        step_state.update_step("t1", "m1", 0, "wrong")


def test_upsert_replaces_existing_message():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "old"}])
    step_state.update_step("t1", "m1", 0, "done")
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "new"}])
    assert step_state.get_steps("t1")["m1"][0]["status"] == "pending"
    assert step_state.get_steps("t1")["m1"][0]["text"] == "new"


def test_render_status_block_empty():
    assert step_state.render_status_block("t1") == ""


def test_render_status_block_has_icons():
    step_state.upsert_steps("t1", "m1", [
        {"index": 0, "text": "abrir spotlight"},
        {"index": 1, "text": "escribir"},
        {"index": 2, "text": "enter"},
    ])
    step_state.update_step("t1", "m1", 0, "done")
    step_state.update_step("t1", "m1", 1, "stuck", note="no carga")
    out = step_state.render_status_block("t1")
    assert "[Estado de pasos]" in out
    assert "1✓" in out and "2✕" in out and "3◯" in out
    assert "no carga" in out
