"""
B13.1′ — the screen-reader agent (Track B, Week 13).

The third subject of the benchmark, and hypothesis H3's: an agent that works
the web the way a blind screen-reader user does. It **perceives only
announcements** — what B9.2's virtual screen reader would say, computed from
Chrome's accessibility tree — and it **acts only by keyboard**: Tab and
Shift+Tab to move, Enter/Space to activate, arrows inside widgets, and typing
into whatever has focus. It never sees an element id and cannot click.

That is the point of including it. A tree agent can still click a roleless,
unnamed div by id; a screen-reader user cannot even reach it if it is not in
the Tab order. So a keyboard trap or a control removed from the Tab order —
invisible to a sighted mouse user — is where this agent should suffer most
(H3), and its results speak for the people WCAG 2.1.1 exists for.

Perception (`observe_announcements`):

    FOCUS: Submit, button
    PAGE (screen reader browse mode, top to bottom):
      Sign in, heading, level 1
      Email, edit
      ...

Both lines come from `verity.agents.virtual_sr` + `announce.predict` — the same
code `verity scan` uses — so the agent hears exactly what Verity predicts a
screen reader announces. Nothing here invents an announcement.

Keyboard-only is enforced, not requested: the env is wrapped in
`hardening.GuardedEnv(allowed={"press", "type"})`, so a click the model emits
anyway is refused with an error the agent sees, exactly as if its screen reader
had no mouse.
"""

from __future__ import annotations

from typing import Optional

from eval.agentbench.agents.tree_agent import TreeAgentResult, run_episode
from eval.agentbench.loop_guard import LoopGuard
from eval.agentbench.providers.base import BaseProvider
from verity.agents.announce import predict
from verity.agents.virtual_sr import _iter_all, browse, load_ax_tree

KEYBOARD_ACTIONS = frozenset({"press", "type"})
MAX_PAGE_LINES = 200

_SR_SYSTEM = """\
You are a blind user operating a web page with a screen reader and a keyboard.
You cannot see the screen and you have no mouse. Each turn you hear:

    FOCUS: <what the screen reader says about the element that has focus>
    PAGE (screen reader browse mode, top to bottom):
      <one announcement per line: name, role, states>

Announcements are "name, role, states" — e.g. "Submit, button" or
"Remember me, checkbox, not checked". A control announced as only its role
("button") has no name: you cannot tell what it does.

You act ONLY with the keyboard. Emit EXACTLY ONE JSON object and nothing else:

    {"reasoning": "...", "action": "press", "key": "Tab"}

Actions:
  press   key    - press a key: "Tab", "Shift+Tab", "Enter", " " (Space),
                   "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight",
                   "Home", "End", "Escape"
  type    text   - type text into the element that has focus
  done           - you believe the task is complete
  report_infeasible - the task CANNOT be done with a screen reader and
                   keyboard (e.g. the control you need cannot be reached or
                   has no name); use this instead of guessing

To reach a control, press Tab (or Shift+Tab) until FOCUS announces it, then
press Enter or Space to activate it, or type into it. If Tab never reaches the
control you need, that is a real barrier: report it rather than guessing."""


def render_announcements(ax_nodes: list[dict], *, max_lines: int = MAX_PAGE_LINES) -> str:
    """
    The agent's observation, from a CDP `getFullAXTree` node list. Pure, so it
    is tested on hand-built trees without a browser.
    """
    tree = load_ax_tree({"nodes": ax_nodes})
    focused = next(
        (n for n in _iter_all(tree)
         if not n.ignored and n.properties.get("focused") is True and n.role not in (None, "RootWebArea")),
        None,
    )
    focus = predict(focused.role, focused.name, focused.states).text if focused else \
        "nothing (focus is on the page itself — press Tab to move to the first control)"
    lines = [a.text for a in browse(tree)]
    more = len(lines) - max_lines
    body = "\n".join("  " + line for line in lines[:max_lines]) or "  (the screen reader announces nothing)"
    if more > 0:
        body += f"\n  … {more} more line(s) not read"
    return f"FOCUS: {focus}\nPAGE (screen reader browse mode, top to bottom):\n{body}"


def observe_announcements(env) -> str:
    """Read the live page's accessibility tree over CDP and render the announcements."""
    page = env.page
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("Accessibility.enable")
        nodes = cdp.send("Accessibility.getFullAXTree")["nodes"]
    finally:
        try:
            cdp.detach()
        except Exception:
            pass
    return render_announcements(nodes)


class ScreenReaderAgent:
    """Announcements in, keystrokes out (B13.1′). Same control loop as every agent."""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        max_steps: int = 25,
        max_tokens: int = 512,
        max_parse_failures: int = 3,
        loop_guard: Optional[LoopGuard] = None,
    ):
        # A keyboard user needs more steps than a clicker (Tab, Tab, Enter),
        # so the default cap is higher; the runner may still pass its own.
        self.provider = provider
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.max_parse_failures = max_parse_failures
        self.loop_guard = loop_guard

    def run(self, env, task: str, seed: int, defect: Optional[str] = None,
            attack: Optional[str] = None) -> TreeAgentResult:
        from eval.agentbench.hardening import GuardedEnv

        guarded = GuardedEnv(env, allowed=KEYBOARD_ACTIONS)
        result = run_episode(
            self.provider, guarded, task, seed, defect, attack,
            system=_SR_SYSTEM, observe=observe_announcements,
            max_steps=self.max_steps, max_tokens=self.max_tokens,
            max_parse_failures=self.max_parse_failures, loop_guard=self.loop_guard,
        )
        result.blocked_actions = list(guarded.blocked)  # clicks it tried and was refused
        return result
