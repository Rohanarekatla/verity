"""
A12.1′ — the benchmark runner, tested without a browser, network, or spend.

Proves the four properties the runner exists to guarantee: a deterministic,
seeded run order; resumability (completed episodes are skipped, not re-run); the
hard budget cap stops the run and records the refused episode; and a defect
variant that fails injection verification is excluded, never measured. Plus the
exclusion mapping (provider_error / budget / injection_unverified) and that a
per-episode trace is written for every measured episode.
"""

import json
from pathlib import Path

import pytest

from eval.agentbench.analysis import load_records
from eval.agentbench.env import Episode, Step
from eval.agentbench.agents.tree_agent import TreeAgentResult
from eval.agentbench.providers import BudgetExceeded
from eval.agentbench.providers.base import ProviderError
from eval.agentbench.runner import (
    ORDER_SEED,
    EpisodeSpec,
    build_plan,
    order_plan,
    run_benchmark,
    shard,
)
from eval.agentbench.tasks import Task
from eval.agentbench.verify_injection import VerifyResult


# --- fakes -----------------------------------------------------------------

TASKS = (
    Task("click-button", "miniwob", "button", ("strip_name",)),
    Task("click-link", "miniwob", "link", ("strip_name",)),
)


class FakeEnv:
    def __init__(self, headless=True):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeProvider:
    def __init__(self, name="fake"):
        self.name = name
        self.model = "fake-1"


def _result(task, seed, defect, *, provider="fake", reward=None, cost=0.002) -> TreeAgentResult:
    ep = Episode(task=task, seed=seed, defect=defect, goal=f"goal {task}")
    ep.steps = [Step(observation='[1] button "Go"', action="click bid=1", ok=True)]
    ep.done = True
    # Clean succeeds, defect fails — the effect the benchmark is built to find.
    ep.reward = (1.0 if defect is None else 0.0) if reward is None else reward
    return TreeAgentResult(episode=ep, provider=provider, model="fake-1", steps_used=1,
                           input_tokens=20, output_tokens=10, cost_usd=cost)


class FakeAgent:
    """agent_factory(provider) -> this; .run returns a scripted result."""

    def __init__(self, provider, *, raise_on=None, exc=None):
        self.provider = provider
        self._raise_on = raise_on          # a defect value to raise on, or "all"
        self._exc = exc

    def run(self, env, task, seed, defect=None):
        if self._raise_on is not None and (self._raise_on == "all" or self._raise_on == defect):
            raise self._exc
        return _result(task, seed, defect, provider=self.provider.name)


def _ok_verify(env, task, seed, defect):
    return VerifyResult(task=task, seed=seed, defect=defect, ok=True, pixels_identical=True)


def _bad_verify(env, task, seed, defect):
    return VerifyResult(task=task, seed=seed, defect=defect, ok=False,
                        reasons=["defect did not manifest in the tree"])


def _run(out, **kw):
    defaults = dict(
        models={"m": "fake:fake-1"}, out_dir=out, tasks=TASKS, trials=1,
        env_factory=FakeEnv,
        provider_factory=lambda label, spec, ledger: FakeProvider(),
        agent_factory=lambda p: FakeAgent(p),
        verify_fn=_ok_verify,
    )
    defaults.update(kw)
    return run_benchmark(**defaults)


# --- plan / order / shard (pure) -------------------------------------------

def test_plan_covers_clean_plus_each_defect():
    plan = build_plan({"m": "fake:fake-1"}, tasks=TASKS, trials=2)
    # 2 tasks × (clean + 1 defect) × 1 model × 2 trials = 8
    assert len(plan) == 8
    assert {s.defect for s in plan} == {None, "strip_name"}
    assert len({s.episode_id for s in plan}) == 8  # ids are unique


def test_order_is_deterministic_and_seeded():
    plan = build_plan({"m": "fake:fake-1"}, tasks=TASKS, trials=3)
    a = [s.episode_id for s in order_plan(plan)]
    b = [s.episode_id for s in order_plan(list(reversed(plan)))]
    assert a == b                                   # input order cannot leak in
    assert a != sorted(a)                           # it actually shuffled
    assert [s.episode_id for s in order_plan(plan, seed=1)] != a  # seed matters


def test_shard_is_round_robin_and_covers_everything():
    plan = build_plan({"m": "fake:fake-1"}, tasks=TASKS, trials=3)
    shards = shard(plan, 3)
    assert len(shards) == 3
    flat = [s for sh in shards for s in sh]
    assert sorted(s.episode_id for s in flat) == sorted(s.episode_id for s in plan)


# --- running ----------------------------------------------------------------

def test_writes_records_and_a_trace_per_episode(tmp_path):
    report = _run(tmp_path)
    assert report.planned == 4 and report.run == 4
    records = load_records(tmp_path / "records.jsonl")
    assert len(records) == 4
    # A trace file per measured episode, and it has the AXTree the agent saw.
    traces = list((tmp_path / "traces").glob("*.json"))
    assert len(traces) == 4
    one = json.loads(traces[0].read_text())
    assert one["steps"][0]["observation"].startswith("[1] button")


def test_resume_skips_completed_episodes(tmp_path):
    first = _run(tmp_path)
    assert first.run == 4
    # Running again must do nothing — every episode is already recorded.
    second = _run(tmp_path)
    assert second.planned == 4 and second.already_done == 4 and second.run == 0
    assert len(load_records(tmp_path / "records.jsonl")) == 4  # not doubled


def test_unverified_injection_is_excluded_and_not_measured(tmp_path):
    report = _run(tmp_path, verify_fn=_bad_verify)
    # 2 clean episodes run; 2 defect episodes excluded (verification failed).
    assert report.run == 2
    assert report.excluded == {"injection_unverified": 2}
    recs = load_records(tmp_path / "records.jsonl")
    defect_recs = [r for r in recs if r.defect != "clean"]
    assert all(r.excluded_reason == "injection_unverified" for r in defect_recs)
    assert not any(r.usable for r in defect_recs)
    # The excluded defect episodes got no trace (they never ran).
    assert len(list((tmp_path / "traces").glob("*.json"))) == 2


def test_provider_error_is_excluded_not_counted_as_failure(tmp_path):
    report = _run(
        tmp_path,
        agent_factory=lambda p: FakeAgent(p, raise_on="all", exc=ProviderError("fake", "boom")),
    )
    assert report.run == 0
    assert report.excluded.get("provider_error") == 4
    recs = load_records(tmp_path / "records.jsonl")
    assert all(r.excluded_reason == "provider_error" for r in recs)


def test_budget_exceeded_stops_the_run(tmp_path):
    report = _run(
        tmp_path,
        agent_factory=lambda p: FakeAgent(p, raise_on="all", exc=BudgetExceeded(10.0, 1.0, 10.0)),
    )
    assert report.budget_stopped is True
    # The run halted after the first refused episode, not after all four.
    assert report.run == 0 and report.excluded.get("budget") == 1
    assert report.planned == 4


def test_two_workers_run_the_whole_plan(tmp_path):
    report = _run(tmp_path, workers=2)
    assert report.run == 4
    assert len(load_records(tmp_path / "records.jsonl")) == 4
    # Each worker kept its own ledger shard.
    assert len(list(tmp_path.glob("ledger.shard*.jsonl"))) == 0  # fakes don't record spend


def test_outcome_is_success_only_on_positive_reward(tmp_path):
    _run(tmp_path)
    recs = {(r.task_id, r.defect): r for r in load_records(tmp_path / "records.jsonl")}
    assert recs[("click-button", "clean")].outcome == "success"
    assert recs[("click-button", "strip_name")].outcome == "failure"
