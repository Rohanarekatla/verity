"""
A15.3 — the ACT test-case runner.

Proves the Verity→ACT outcome mapping (a definite fail stands alone; a
needs-review is cantTell, never a pass), and — the honesty requirement — that a
cantTell on a decidable case counts against the headline pass rate, is reported
as undecided, and is excluded from the decided pass rate.
"""

from eval.act_runner import (
    ActCase,
    load_cases,
    map_outcome,
    run_act,
)


def test_map_outcome_fail_stands_alone():
    findings = [{"sc": {"id": "1.4.3"}, "outcome": "fail", "provenance": "authoritative"}]
    assert map_outcome(findings, sc="1.4.3") == "failed"


def test_map_outcome_needs_review_is_canttell_not_pass():
    findings = [{"sc": {"id": "1.1.1"}, "outcome": "cantTell", "provenance": "needs review"}]
    assert map_outcome(findings, sc="1.1.1") == "cantTell"


def test_map_outcome_no_relevant_finding_is_pass():
    findings = [{"sc": {"id": "2.1.1"}, "outcome": "fail"}]
    assert map_outcome(findings, sc="1.4.3") == "passed"  # different SC, not relevant


def _scan_fn(table):
    return lambda url: table.get(url, [])


def test_run_act_aggregates_per_rule_and_counts_matches():
    cases = [
        ActCase("contrast", "c1", "u-fail", expected="failed", sc="1.4.3"),
        ActCase("contrast", "c2", "u-pass", expected="passed", sc="1.4.3"),
    ]
    table = {"u-fail": [{"sc": {"id": "1.4.3"}, "outcome": "fail"}], "u-pass": []}
    report = run_act(cases, _scan_fn(table))
    r = report.rules["contrast"]
    assert r.cases == 2 and r.consistent == 2 and r.undecided == 0
    assert r.pass_rate == 1.0


def test_canttell_is_undecided_not_a_pass():
    # Case expects passed; Verity returns needs-review -> cantTell.
    cases = [ActCase("alt", "a1", "u", expected="passed", sc="1.1.1")]
    table = {"u": [{"sc": {"id": "1.1.1"}, "outcome": "cantTell", "provenance": "needs review"}]}
    report = run_act(cases, _scan_fn(table))
    r = report.rules["alt"]
    assert r.consistent == 0 and r.undecided == 1
    assert r.pass_rate == 0.0                     # counts against the headline
    assert r.decided_pass_rate != r.decided_pass_rate  # NaN: nothing was decided


def test_totals_report_both_rates():
    cases = [
        ActCase("r", "1", "fail", expected="failed", sc="x"),
        ActCase("r", "2", "ct", expected="passed", sc="x"),   # undecided
    ]
    table = {"fail": [{"sc": {"id": "x"}, "outcome": "fail"}],
             "ct": [{"sc": {"id": "x"}, "outcome": "cantTell"}]}
    t = run_act(cases, _scan_fn(table)).totals
    assert t["cases"] == 2 and t["consistent"] == 1 and t["undecided"] == 1
    assert t["pass_rate"] == 0.5                  # 1 of 2 overall
    assert t["decided_pass_rate"] == 1.0          # 1 of 1 decided


def test_load_cases(tmp_path):
    import json

    p = tmp_path / "cases.json"
    p.write_text(json.dumps([
        {"rule_id": "r1", "case_id": "c1", "url": "u1", "expected": "passed", "sc": "1.4.3"},
    ]), encoding="utf-8")
    cases = load_cases(p)
    assert len(cases) == 1 and cases[0].rule_id == "r1" and cases[0].sc == "1.4.3"
