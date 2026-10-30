"""
A13.2′ — the injection-attack track and hijack scoring.

Proves the canary detector is deterministic (an action carrying the canary is a
hijack, nothing else is), the attack catalogue records who can perceive each
vector, the rate aggregates per cell, and the attack-track runner writes hijack
records on a clean page, resumably.
"""

import json

from eval.agentbench.attacks import (
    ATTACKS,
    ATTACKS_BY_ID,
    CANARY,
    HijackRecord,
    assess_hijack,
    hijack_rate,
)
from eval.agentbench.env import Episode, Step
from eval.agentbench.agents.tree_agent import TreeAgentResult
from eval.agentbench.runner import build_attack_plan, run_attack_track
from eval.agentbench.tasks import Task


# --- hijack detection (pure) -----------------------------------------------

def _episode(actions):
    ep = Episode(task="t", seed=0, defect=None, goal="g")
    ep.steps = [Step(observation="", action=a, ok=True) for a in actions]
    ep.done, ep.reward = True, 1.0
    return ep


def test_canary_action_is_a_hijack():
    a = assess_hijack(_episode(["click bid=1", f'fill bid=2 text="{CANARY}"']))
    assert a.hijacked is True and a.step == 2


def test_cooperative_agent_is_not_hijacked():
    a = assess_hijack(_episode(["click bid=1", "fill bid=2 text=\"hello\"", "done"]))
    assert a.hijacked is False


def test_canary_match_is_case_insensitive():
    assert assess_hijack(_episode([f'type text="{CANARY.lower()}"'])).hijacked is True


def test_attacks_declare_perceivability():
    aria = ATTACKS_BY_ID["hidden_aria"]
    # A DOM/vision agent cannot perceive an aria-only, off-screen injection.
    assert "browser_use" not in aria.perceivable_by
    assert "tree" in aria.perceivable_by and "screen_reader" in aria.perceivable_by
    # A visible banner reaches everyone.
    assert set(ATTACKS_BY_ID["visible_banner"].perceivable_by) == {"tree", "browser_use", "screen_reader"}


def test_hijack_rate_aggregates_and_skips_excluded():
    recs = [
        HijackRecord(episode_id="e1", task_id="t", agent="tree", provider="p", model="m",
                     attack="hidden_aria", vector="hidden_aria", trial=0, perceivable=True,
                     hijacked=True, task_outcome="failure"),
        HijackRecord(episode_id="e2", task_id="t", agent="tree", provider="p", model="m",
                     attack="hidden_aria", vector="hidden_aria", trial=1, perceivable=True,
                     hijacked=False, task_outcome="success"),
        HijackRecord(episode_id="e3", task_id="t", agent="tree", provider="p", model="m",
                     attack="hidden_aria", vector="hidden_aria", trial=2, perceivable=True,
                     hijacked=True, task_outcome="failure", excluded_reason="provider_error"),
    ]
    cells = hijack_rate(recs)
    assert len(cells) == 1
    c = cells[0]
    assert c.n == 2 and c.hijacked == 1 and c.rate == 0.5  # excluded one dropped


# --- the attack-track runner -----------------------------------------------

TASKS = (Task("click-button", "miniwob", "button", ("strip_name",)),)


class FakeEnv:
    def __init__(self, headless=True):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeProvider:
    name = "fake"
    model = "fake-1"


class HijackableAgent:
    """Gets hijacked only by the visible_banner attack (and types the canary);
    otherwise does the task cleanly."""

    def __init__(self, provider):
        self.provider = provider

    def run(self, env, task, seed, defect=None, attack=None):
        actions = ["click bid=1"]
        if attack == "visible_banner":
            actions.append(f'fill bid=2 text="{CANARY}"')
        ep = Episode(task=task, seed=seed, defect=None, goal="g")
        ep.steps = [Step(observation="[1] button", action=a, ok=True) for a in actions]
        ep.done, ep.reward = True, 1.0
        return TreeAgentResult(episode=ep, provider="fake", model="fake-1", steps_used=len(actions))


def _run(out, **kw):
    defaults = dict(
        models={"m": "fake:fake-1"}, out_dir=out, tasks=TASKS, agents=("tree",), trials=1,
        env_factory=FakeEnv,
        provider_factory=lambda label, spec, ledger: FakeProvider(),
        agent_factory=lambda name, p: HijackableAgent(p),
    )
    defaults.update(kw)
    return run_attack_track(**defaults)


def test_attack_plan_covers_every_attack():
    plan = build_attack_plan({"m": "fake:x"}, tasks=TASKS, agents=("tree",), trials=1)
    assert len(plan) == len(ATTACKS)
    assert {s.attack.id for s in plan} == {a.id for a in ATTACKS}


def test_attack_track_records_hijacks_and_perceivability(tmp_path):
    report = _run(tmp_path)
    assert report.run == len(ATTACKS)
    recs = [HijackRecord.model_validate(json.loads(l))
            for l in (tmp_path / "hijacks.jsonl").read_text().splitlines() if l.strip()]
    by_attack = {r.attack: r for r in recs}
    # Only the visible banner hijacked this agent.
    assert by_attack["visible_banner"].hijacked is True
    assert by_attack["hidden_aria"].hijacked is False
    # The tree agent cannot perceive... actually it CAN perceive hidden_aria.
    assert by_attack["hidden_aria"].perceivable is True
    # Task still completed under the (non-hijacking) attacks.
    assert all(r.task_outcome == "success" for r in recs)


def test_attack_track_resumes(tmp_path):
    first = _run(tmp_path)
    assert first.run == len(ATTACKS)
    second = _run(tmp_path)
    assert second.run == 0 and second.already_done == len(ATTACKS)
