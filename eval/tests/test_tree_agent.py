"""
A10.4 — the tree-only agent.

The loop logic is tested against a fake provider and a fake env (no browser, no
network): step cap, the `done` and `report_infeasible` exits, parse-failure
abort, token/cost accounting, and provider-error propagation. Parsing is tested
on the messy shapes a real model produces. The action schema is run through the
real schema linter so the escape rule is enforced here, not assumed. A skippable
smoke test drives the real MiniWoB env to prove the agent and env integrate.
"""

import pytest

from eval.agentbench.agents.tree_agent import (
    AgentAction,
    TreeAgent,
    action_json_schema,
    _parse_action,
)
from eval.agentbench.providers.base import Completion, Message, ProviderError, Timing, Usage


# --- fakes -----------------------------------------------------------------

def _completion(text: str, *, inp=10, out=5, cost=0.001) -> Completion:
    return Completion(
        provider="fake", model="fake-1", text=text,
        usage=Usage(input_tokens=inp, output_tokens=out),
        timing=Timing(wall_s=0.01), cost_usd=cost,
    )


class FakeProvider:
    """Returns scripted completions; records what it was asked."""
    name = "fake"
    model = "fake-1"

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def complete(self, messages, *, system=None, max_tokens=512, tag=None, **kw) -> Completion:
        self.calls += 1
        if isinstance(self._replies[min(self.calls - 1, len(self._replies) - 1)], Exception):
            raise self._replies[self.calls - 1]
        reply = self._replies[min(self.calls - 1, len(self._replies) - 1)]
        return reply if isinstance(reply, Completion) else _completion(reply)


class FakeEnv:
    """A scriptable env: `done_after` actions succeed, then status() reports done."""

    def __init__(self, obs="[1] button \"Submit\"", done_after=None, reward=1.0, act_error=None):
        self._obs = obs
        self._done_after = done_after
        self._reward = reward
        self._act_error = act_error
        self.acted = []
        self._acts = 0

    def reset(self, task, seed, defect=None):
        return f"goal for {task}"

    def observe(self):
        return self._obs

    def act(self, action):
        self.acted.append(action)
        self._acts += 1
        return self._act_error

    def status(self):
        if self._done_after is not None and self._acts >= self._done_after:
            return True, self._reward
        return False, 0.0


# --- loop behaviour --------------------------------------------------------

def test_agent_completes_a_task_and_reads_reward():
    env = FakeEnv(done_after=1, reward=1.0)
    agent = TreeAgent(FakeProvider(['{"action":"click","bid":1}']))
    r = agent.run(env, "click-button", seed=0)
    assert r.episode.done is True
    assert r.episode.reward == 1.0
    assert env.acted == [{"action": "click", "bid": 1}]
    assert r.input_tokens == 10 and r.output_tokens == 5
    assert r.cost_usd == pytest.approx(0.001)


def test_report_infeasible_stops_without_acting():
    env = FakeEnv(done_after=None)
    agent = TreeAgent(FakeProvider(['{"reasoning":"no named button","action":"report_infeasible"}']))
    r = agent.run(env, "click-button", seed=0)
    assert r.infeasible is True
    assert r.episode.done is False
    assert env.acted == []  # it declined rather than guessing a click


def test_done_action_reads_final_status():
    env = FakeEnv(done_after=None, reward=0.0)
    agent = TreeAgent(FakeProvider(['{"action":"done"}']))
    r = agent.run(env, "t", seed=0)
    assert r.episode.steps[-1].action == "done"
    assert r.episode.done is False  # env never reported done; we don't fake success


def test_step_cap_is_enforced():
    env = FakeEnv(done_after=None)  # never completes
    agent = TreeAgent(FakeProvider(['{"action":"click","bid":1}']), max_steps=4)
    r = agent.run(env, "t", seed=0)
    assert r.steps_used == 4
    assert len(env.acted) == 4


def test_parse_failures_abort_after_cap():
    env = FakeEnv(done_after=None)
    agent = TreeAgent(FakeProvider(["not json at all"]), max_parse_failures=3, max_steps=10)
    r = agent.run(env, "t", seed=0)
    assert r.parse_failures == 3  # aborted at the cap, didn't burn all 10 steps
    assert env.acted == []


def test_provider_error_propagates_as_episode_error():
    env = FakeEnv()
    agent = TreeAgent(FakeProvider([ProviderError("fake", "boom")]))
    with pytest.raises(ProviderError):
        agent.run(env, "t", seed=0)


def test_token_and_cost_accumulate_across_steps():
    env = FakeEnv(done_after=3)
    agent = TreeAgent(FakeProvider(['{"action":"click","bid":1}']), max_steps=5)
    r = agent.run(env, "t", seed=0)
    assert r.input_tokens == 30 and r.output_tokens == 15  # 3 calls
    assert r.cost_usd == pytest.approx(0.003)


# --- parsing ---------------------------------------------------------------

def test_parse_plain_json():
    a = _parse_action('{"action":"click","bid":3}')
    assert a.action == "click" and a.bid == 3


def test_parse_fenced_json_with_prose():
    text = 'I will click it.\n```json\n{"action":"click","bid":7}\n```\nDone.'
    a = _parse_action(text)
    assert a.action == "click" and a.bid == 7


def test_parse_takes_the_final_object():
    text = 'First idea {"action":"press","key":"Tab"} but actually {"action":"click","bid":2}'
    a = _parse_action(text)
    assert a.action == "click" and a.bid == 2


def test_parse_rejects_unknown_action():
    assert _parse_action('{"action":"teleport","bid":1}') is None


def test_parse_rejects_garbage():
    assert _parse_action("no json here") is None
    assert _parse_action("") is None


def test_to_env_action_only_includes_present_fields():
    a = AgentAction(action="fill", bid=2, text="hi")
    assert a.to_env_action() == {"action": "fill", "bid": 2, "text": "hi"}
    assert AgentAction(action="press", key="Enter").to_env_action() == {"action": "press", "key": "Enter"}


# --- schema linter: the escape rule is enforced ----------------------------

def test_action_schema_passes_the_linter_with_report_infeasible_escape():
    from verity.schema_lint import ESCAPES, lint_json_schema

    # The action set's escape is BrowserGym's report_infeasible, not "unknown".
    violations = lint_json_schema(
        action_json_schema(), name="AgentAction",
        escapes=ESCAPES | {"report_infeasible"},
    )
    assert violations == [], f"action schema violates the escape rule: {violations}"


def test_action_schema_would_fail_without_the_escape():
    """Guard the guard: the linter really is checking the action enum."""
    from verity.schema_lint import ESCAPES, lint_json_schema

    violations = lint_json_schema(action_json_schema(), name="AgentAction", escapes=ESCAPES)
    assert any("action" in v.field for v in violations), "linter should flag the enum without report_infeasible"


# --- real-env smoke test (skipped without Chromium) ------------------------

def _real_env_available() -> bool:
    """Chromium installed AND the vendored MiniWoB tasks present on disk."""
    from eval.agentbench.env import MINIWOB, chromium_path

    return chromium_path() is not None and (MINIWOB / "click-test.html").exists()


@pytest.mark.skipif(
    not _real_env_available(),
    reason="needs Chromium + the vendored MiniWoB tasks (eval/agentbench/vendor/, fetched separately)",
)
def test_agent_runs_against_the_real_env():
    from eval.agentbench.env import MiniWoBEnv

    # A provider that always declines: we are testing env+agent integration
    # (reset → observe → loop → trace), not task success.
    agent = TreeAgent(FakeProvider(['{"action":"report_infeasible"}']))
    with MiniWoBEnv(headless=True) as env:
        r = agent.run(env, "click-test", seed=1)
    assert r.infeasible is True
    assert len(r.episode.steps) == 1
    assert r.episode.steps[0].observation  # a non-empty accessibility tree was rendered
    assert r.episode.goal
