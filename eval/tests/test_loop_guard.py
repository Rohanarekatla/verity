"""
A13.3 — state labelling and the loop guard.

Proves the state label is stable under cosmetic whitespace and distinct for
different states, and that the guard trips on a repeated (state, action) pair
and on thrashing between a few states — and, wired into an agent, ends a stuck
episode as a task failure rather than burning the whole step budget.
"""

from eval.agentbench.agents.tree_agent import TreeAgent
from eval.agentbench.loop_guard import LoopGuard, state_label
from eval.agentbench.providers.base import Completion, Timing, Usage


def test_state_label_is_whitespace_stable_and_distinct():
    a = state_label('[1] button "Go"\n[2] textbox')
    b = state_label('[1] button "Go"   \n[2] textbox\n')  # trailing space / newline
    c = state_label('[1] button "Stop"\n[2] textbox')
    assert a == b          # cosmetic difference collapses
    assert a != c          # a real difference does not


def test_guard_trips_on_repeated_state_action():
    g = LoopGuard(max_repeats=3)
    s = state_label("same page")
    assert g.record(s, "click bid=1") is False
    assert g.record(s, "click bid=1") is False
    assert g.record(s, "click bid=1") is True     # third time
    assert "repeated action" in g.tripped_on


def test_guard_trips_on_state_thrash():
    g = LoopGuard(max_repeats=99, max_state_visits=4)
    s = state_label("page")
    trips = [g.record(s, f"click bid={i}") for i in range(4)]
    assert trips[-1] is True
    assert "revisited" in g.tripped_on


def test_reset_clears_counts():
    g = LoopGuard(max_repeats=2)
    s = state_label("p")
    g.record(s, "a")
    g.reset()
    assert g.record(s, "a") is False  # count started over


# --- wired into an agent ---------------------------------------------------

class _StuckEnv:
    """Never completes and always shows the same page, so a clicking agent
    repeats the same (state, action) forever."""

    def reset(self, task, seed, defect=None):
        return "goal"

    def observe(self):
        return '[1] button "Go"'

    def act(self, action):
        return None

    def status(self):
        return False, 0.0


class _ClickProvider:
    name = "fake"
    model = "fake-1"

    def complete(self, messages, *, system=None, max_tokens=512, tag=None, **kw):
        return Completion(provider="fake", model="fake-1", text='{"action":"click","bid":1}',
                          usage=Usage(input_tokens=5, output_tokens=2), timing=Timing(wall_s=0.0),
                          cost_usd=0.0)


def test_agent_with_guard_stops_early_instead_of_exhausting_steps():
    guarded = TreeAgent(_ClickProvider(), max_steps=15, loop_guard=LoopGuard(max_repeats=3))
    r = guarded.run(_StuckEnv(), "t", seed=0)
    assert r.looped is True
    assert r.steps_used < 15               # stopped well before the cap
    assert not r.episode.done

    # Without a guard the same agent runs to the step cap.
    unguarded = TreeAgent(_ClickProvider(), max_steps=15)
    r2 = unguarded.run(_StuckEnv(), "t", seed=0)
    assert r2.looped is False and r2.steps_used == 15
