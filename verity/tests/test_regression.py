"""
B7.4 — regression gating against a baseline.

Week 7 gate: on a page with 50 pre-existing findings, introducing one new
defect fails the build on exactly that one.
Week 8 gate: the build fails only on *new authoritative* findings.
"""

import pytest

from verity.models.schemas import (
    AuditReport, Confidence, Evidence, Finding, Latency, Level, Modality,
    Provenance, Severity, SuccessCriterion,
)
from verity.report.baseline import build_baseline, write_baseline
from verity.report.policy import DEFAULT_POLICY
from verity.report.regression import (
    BaselineIncompatible, gate_against_baseline, open_baseline,
)


def _finding(selector, provenance=Provenance.AUTHORITATIVE) -> Finding:
    ai = provenance is Provenance.AI_ASSISTED
    return Finding(
        id=f"color-contrast-{selector.strip('#')}",
        rule_id="color-contrast",
        sc=SuccessCriterion(id="1.4.3", name="Contrast (Minimum)",
                            level=Level.AA, modality=Modality.DETERMINISTIC),
        provenance=provenance,
        severity=Severity.SERIOUS,
        confidence=(Confidence(score=0.7, method="vision", model="qwen2.5-vl-7b-4bit")
                    if ai else Confidence(score=1.0, method="deterministic")),
        agent="axe-core",
        outcome="fail",
        message="Insufficient contrast",
        evidence=Evidence(dom_selector=selector),
        page_state_hash="h",
    )


def _report(findings, ruleset="1.0.0", target="https://example.com") -> AuditReport:
    return AuditReport(
        target=target, standard="WCAG2.2-AA", findings=list(findings),
        conformance={}, verity_version="0.1.0", ruleset_version=ruleset,
        latency=Latency(render_seconds=1.0, analysis_seconds=0.5, total_seconds=2.0),
    )


FIFTY = [_finding(f"#old-{i}") for i in range(50)]


# --- the gates ---------------------------------------------------------------

def test_fifty_old_findings_plus_one_new_gates_on_exactly_that_one():
    """Week 7's gate, literally."""
    baseline = build_baseline(_report(FIFTY))
    scan = _report(FIFTY + [_finding("#new-defect")])

    result = gate_against_baseline(baseline, scan, DEFAULT_POLICY)

    assert [f.evidence.dom_selector for f in result.gating] == ["#new-defect"]
    assert len(result.diff.unchanged) == 50


def test_fifty_old_findings_and_nothing_new_does_not_gate():
    baseline = build_baseline(_report(FIFTY))
    result = gate_against_baseline(baseline, _report(FIFTY), DEFAULT_POLICY)
    assert result.gating == []


def test_a_new_ai_assisted_finding_does_not_gate_under_the_default_policy():
    """Week 8's gate: only new *authoritative* findings fail the build."""
    baseline = build_baseline(_report(FIFTY))
    scan = _report(FIFTY + [_finding("#maybe", provenance=Provenance.AI_ASSISTED)])

    result = gate_against_baseline(baseline, scan, DEFAULT_POLICY)

    assert len(result.diff.new) == 1, "it is new, and the diff says so"
    assert result.gating == [], "but it is not authoritative, so it annotates only"


def test_regression_is_keyed_to_ruleset_and_corpus_hash():
    baseline = build_baseline(_report(FIFTY))
    result = gate_against_baseline(baseline, _report(FIFTY), DEFAULT_POLICY)
    assert result.key.ruleset_version == "1.0.0"
    assert result.key.corpus_hash == baseline.baseline_id


# --- refusing a meaningless diff ----------------------------------------------

def test_ruleset_mismatch_is_refused_not_guessed():
    """
    New rules produce findings nobody in this PR introduced. Gating on them
    would fail the build on old defects — the exact uninstall scenario.
    """
    baseline = build_baseline(_report(FIFTY, ruleset="1.0.0"))
    with pytest.raises(BaselineIncompatible, match="re-recorded"):
        gate_against_baseline(baseline, _report(FIFTY, ruleset="2.0.0"), DEFAULT_POLICY)


def test_signature_scheme_mismatch_is_refused():
    baseline = build_baseline(_report(FIFTY))
    baseline.validator_version = "1.0.0"  # an older signature scheme
    with pytest.raises(BaselineIncompatible, match="re-recorded"):
        gate_against_baseline(baseline, _report(FIFTY), DEFAULT_POLICY)


def test_different_target_still_diffs():
    """A local file has a different file:// URI on a laptop and in CI."""
    baseline = build_baseline(_report(FIFTY, target="file:///C:/dev/site/index.html"))
    scan = _report(FIFTY, target="file:///home/runner/site/index.html")
    assert gate_against_baseline(baseline, scan, DEFAULT_POLICY).gating == []


def test_missing_baseline_file_is_an_error(tmp_path):
    with pytest.raises(BaselineIncompatible, match="does not exist"):
        open_baseline(tmp_path / "nope.json")


def test_no_baseline_means_no_baseline_gating():
    assert open_baseline(None) is None


# --- end to end through the CLI -----------------------------------------------

@pytest.fixture
def cli_with_fixed_report(monkeypatch):
    """Run the real CLI gating path with a canned report and no browser."""
    from verity import cli

    holder = {}

    async def fake_scan_url(**_kwargs):
        return holder["report"]

    monkeypatch.setattr(cli, "scan_url", fake_scan_url)
    monkeypatch.setattr(cli, "report_expired_waivers", lambda *a, **k: [])
    return cli, holder


@pytest.mark.asyncio
async def test_cli_with_baseline_fails_only_on_the_new_defect(tmp_path, cli_with_fixed_report, capsys):
    cli, holder = cli_with_fixed_report
    path = tmp_path / "baseline.json"
    write_baseline(build_baseline(_report(FIFTY)), path)

    holder["report"] = _report(FIFTY)
    assert await cli.run_cli_scan("https://example.com", baseline_path=str(path)) == cli.EXIT_OK

    holder["report"] = _report(FIFTY + [_finding("#new-defect")])
    assert await cli.run_cli_scan("https://example.com", baseline_path=str(path)) == cli.EXIT_GATING_FINDINGS
    out = capsys.readouterr().out
    assert "NEW (1)" in out and "+ 1.4.3  color-contrast  #new-defect" in out


@pytest.mark.asyncio
async def test_cli_without_baseline_still_gates_on_everything(cli_with_fixed_report):
    cli, holder = cli_with_fixed_report
    holder["report"] = _report(FIFTY)
    assert await cli.run_cli_scan("https://example.com") == cli.EXIT_GATING_FINDINGS


@pytest.mark.asyncio
async def test_cli_incompatible_or_missing_baseline_exits_2(tmp_path, cli_with_fixed_report):
    """Our config is the problem, not the page: exit 2, never 1 or 0."""
    cli, holder = cli_with_fixed_report
    holder["report"] = _report(FIFTY, ruleset="2.0.0")

    path = tmp_path / "baseline.json"
    write_baseline(build_baseline(_report(FIFTY, ruleset="1.0.0")), path)
    assert await cli.run_cli_scan("https://example.com", baseline_path=str(path)) == cli.EXIT_SCAN_ERROR

    missing = tmp_path / "missing.json"
    assert await cli.run_cli_scan("https://example.com", baseline_path=str(missing)) == cli.EXIT_SCAN_ERROR
