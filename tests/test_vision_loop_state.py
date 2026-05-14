from helpdesk_app.vision_loop import loop as loop_mod
from helpdesk_app.vision_loop.events import create_run
from helpdesk_app.vision_loop.schema import LoopDecision


class FakeCapture:
    def __init__(self):
        self.png_b64 = "ZmFrZQ=="
        self.thumb_b64 = "ZmFrZQ=="
        self.width = 100
        self.height = 100


def test_loop_stops_on_done_immediately():
    state = create_run("dummy")
    decisions = iter([LoopDecision(reasoning="ya estaba", done=True)])

    def fake_capture():
        return FakeCapture()

    def fake_next_action(goal, png, history, os_hint=None):
        return next(decisions)

    executed = []

    def fake_execute(action):
        executed.append(action)

    outcome = loop_mod.run_loop(
        state,
        max_steps=5,
        total_timeout_s=10,
        capture_fn=fake_capture,
        actor_fn=fake_next_action,
        execute_fn=fake_execute,
        sleep_fn=lambda s: None,
    )
    assert outcome.status == "done"
    assert executed == []


def test_loop_executes_then_done():
    state = create_run("dummy")
    decisions = iter([
        LoopDecision(
            reasoning="primer paso",
            action={"type": "hotkey", "keys": ["LeftCmd", "Space"], "delayMs": 100},
        ),
        LoopDecision(reasoning="hecho", done=True),
    ])

    def fake_capture():
        return FakeCapture()

    def fake_next_action(goal, png, history, os_hint=None):
        return next(decisions)

    executed = []

    def fake_execute(action):
        executed.append(action.type)

    outcome = loop_mod.run_loop(
        state, max_steps=5, total_timeout_s=10,
        capture_fn=fake_capture, actor_fn=fake_next_action,
        execute_fn=fake_execute, sleep_fn=lambda s: None,
    )
    assert outcome.status == "done"
    assert executed == ["hotkey"]


def test_loop_stops_on_max_steps():
    state = create_run("dummy")

    def decision_factory():
        while True:
            yield LoopDecision(
                reasoning="seguir",
                action={"type": "wait", "delayMs": 1},
            )

    gen = decision_factory()

    def fake_capture():
        return FakeCapture()

    def fake_next_action(goal, png, history, os_hint=None):
        return next(gen)

    def fake_execute(action):
        pass

    outcome = loop_mod.run_loop(
        state, max_steps=3, total_timeout_s=10,
        capture_fn=fake_capture, actor_fn=fake_next_action,
        execute_fn=fake_execute, sleep_fn=lambda s: None,
    )
    assert outcome.status == "max_steps"
