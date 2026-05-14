from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from helpdesk_app.desktop_plan import DesktopAction


class LoopDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(..., max_length=400)
    action: DesktopAction | None = None
    done: bool = False
    fail: bool = False
    needs_user: bool = False
    reason: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def _exactly_one_outcome(self):
        terminals = [self.done, self.fail, self.needs_user]
        n_terminals = sum(bool(x) for x in terminals)
        if n_terminals > 1:
            raise ValueError("done/fail/needs_user are mutually exclusive")
        if n_terminals == 0 and self.action is None:
            raise ValueError("Either provide an action, or set done/fail/needs_user")
        if n_terminals >= 1 and self.action is not None:
            self.action = None
        return self
