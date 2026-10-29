"""
A10.4 pilot harness — aggregation logic, tested without a browser or network.

Proves the pilot: runs the matrix, scores success from the env reward (never an
LLM), separates clean from defect cells, excludes provider errors from the
success rate, and renders the report the W10 gate records.
"""

import pytest

from eval.agentbench.pilot import CellStats, format_report, run_pilot
from eval.agentbench.providers.base import Completion, ProviderError, Timing, Usage


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, *, fail=False):
        self._fail = fail

    def complete(self, messages, *, system=None, max_tokens=512, tag=None, **kw):
        if self._fail:
            raise ProviderError("fake", "boom")
        return Completion(
            provider="fake", model="fake-1", text='{"action":"click","bid":1}',
            usage=Usage(input_tokens=20, output_tokens=10), timing=Timing(wall_s=0.01),
            cost_usd=0.002,
        )


class FakePilotEnv:
    """Context-manager env: clean variants succeed, defect variants fail."""

    def __init__(self, headless=True):
        self._defect = None
        self._acts = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def reset(self, task, seed, defect=None):
        self._defect = defect
        self._acts = 0
        return f"goal {task}"

    def observe(self):
        return '[1] button "Go"'

    def act(self, action):
        self._acts += 1
        return None

    def status(self):
        if self._acts >= 1:
            return True, (1.0 if self._defect is None else 0.0)
        return False, 0.0


def test_pilot_separates_clean_from_defect_success():
    models = {"frontier": FakeProvider(), "local": FakeProvider()}
    cells = run_pilot(
        models, tasks=("t1",), variants={"clean": None, "stripped": "stripName"},
        trials=3, env_factory=FakePilotEnv,
    )
    assert len(cells) == 4  # 2 models × 1 task × 2 variants
    by = {(c.model, c.variant): c for c in cells}
    assert by[("frontier", "clean")].success_rate == 1.0
    assert by[("frontier", "stripped")].success_rate == 0.0
    # tokens/cost recorded per trial
    assert by[("local", "clean")].tokens == [30, 30, 30]
    assert by[("local", "clean")].cost_total == pytest.approx(0.006)


def test_provider_errors_excluded_from_success_rate():
    cells = run_pilot(
        {"broken": FakeProvider(fail=True)}, tasks=("t1",),
        variants={"clean": None}, trials=4, env_factory=FakePilotEnv,
    )
    cell = cells[0]
    assert cell.n == 4 and cell.errors == 4
    assert cell.success_rate == 0.0  # scored = n - errors = 0, no division by zero
    assert cell.tokens == []


def test_cellstats_variance_is_reported():
    c = CellStats(model="m", task="t", variant="v")
    c.tokens = [10, 20, 30]
    assert c.tokens_mean == 20.0
    assert c.tokens_sd > 0


def test_format_report_renders_cells():
    cells = run_pilot(
        {"m": FakeProvider()}, tasks=("t1",), variants={"clean": None}, trials=2,
        env_factory=FakePilotEnv,
    )
    md = format_report(cells)
    assert "AgentBench pilot" in md
    assert "| m | t1 | clean |" in md
    assert "Total cost:" in md
