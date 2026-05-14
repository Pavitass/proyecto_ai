import pytest
from pydantic import ValidationError
from helpdesk_app.vision_loop.schema import LoopDecision

def test_done_decision_is_valid_without_action():
    d = LoopDecision(reasoning="ya está", done=True)
    assert d.done is True
    assert d.action is None

def test_action_decision_requires_action_payload():
    d = LoopDecision(
        reasoning="abrir Spotlight",
        action={"type": "hotkey", "keys": ["LeftCmd", "Space"], "delayMs": 400},
    )
    assert d.action.type == "hotkey"

def test_action_must_be_present_unless_terminal():
    with pytest.raises(ValidationError):
        LoopDecision(reasoning="...")

def test_reasoning_length_capped():
    with pytest.raises(ValidationError):
        LoopDecision(reasoning="x" * 500, done=True)
