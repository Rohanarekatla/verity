"""
A14.1′ — a browser environment for an arbitrary URL.

`verity agent-check` runs the same tree agent the benchmark uses, but against a
real site instead of a MiniWoB task. `WebEnv` is `MiniWoBEnv` with the MiniWoB
episode machinery removed: it navigates to a URL and reuses the exact same
accessibility-tree observation, DOM observation, and action model, so the agent
cannot tell it is driving a real page rather than a benchmark one — the point of
agent-check is that it is the same agent.

There is no environment reward on a real site, so `status()` never reports a
solve; success is decided by `agent_check` from the caller's `--success` spec
(the deterministic evaluators), never by this env and never by a model.
"""

from __future__ import annotations

import json
from typing import Optional

from eval.agentbench.env import ATTACKS_JS, DEFECTS_JS, MiniWoBEnv


class WebEnv(MiniWoBEnv):
    """Drive one real URL with the benchmark's observation/action model."""

    def __init__(self, url: str, goal: str, *, headless: bool = True,
                 defect: Optional[str] = None, viewport: tuple[int, int] = (1280, 900)):
        super().__init__(headless=headless)
        self.url = url
        self.goal = goal
        self._default_defect = defect
        self._vw, self._vh = viewport

    def reset(self, task: Optional[str] = None, seed: int = 0, defect: Optional[str] = None) -> str:
        """Navigate to the URL (ignoring the MiniWoB `task`/`seed`), optionally
        inject a defect, and return the task text as the agent's goal."""
        if self.page:
            self.page.close()
        self.page = self.browser.new_page(viewport={"width": self._vw, "height": self._vh})
        self.page.add_init_script(DEFECTS_JS)
        self.page.add_init_script(ATTACKS_JS)
        self.page.goto(self.url, wait_until="load")
        self._settle()
        injected = defect if defect is not None else self._default_defect
        if injected:
            self.page.evaluate(f"window.__verityDefect({json.dumps(injected)})")
            self._settle()
        return self.goal

    def status(self) -> tuple[bool, float]:
        # A real site has no env reward: agent-check decides success from the
        # --success spec, never this env. Reported as "not solved" so the agent
        # runs to its own `done` / `report_infeasible` / the step cap.
        return (False, 0.0)
