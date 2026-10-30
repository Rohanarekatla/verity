"""
A15.3 — the ACT test-case runner (compressed).

W3C's ACT Rules each ship test cases with an expected outcome. Running Verity
against them and publishing the per-rule pass rate is "the cheapest credibility
available to an unknown open-source tool" — but only if the number is honest,
which here means two things:

1. **`cantTell` is not a pass.** Verity returns three outcomes; an ACT runner
   that silently scored a `cantTell` as whichever answer the case expected would
   inflate the pass rate. Here a `cantTell` on a case that expects `passed` or
   `failed` is counted as *undecided*, reported in its own column, and excluded
   from the decided pass rate — never laundered into a pass.

2. **Both rates are published.** The headline `pass_rate` counts only exact
   matches over all cases (undecided included in the denominator); the
   `decided_pass_rate` excludes the undecided. Reporting one without the other
   is how a pass rate lies.

The scan is injected (`scan_fn(url) -> findings`), so the mapping and the
aggregation are tested with a fake engine, no browser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# ACT's outcome vocabulary.
ACT_OUTCOMES = ("passed", "failed", "inapplicable", "cantTell")


@dataclass(frozen=True)
class ActCase:
    """One ACT test case: the rule it tests, where the page is, and the expected
    outcome. `sc` scopes which of a scan's findings count for this rule."""

    rule_id: str
    case_id: str
    url: str
    expected: str                 # passed | failed | inapplicable | cantTell
    sc: Optional[str] = None       # the WCAG SC id this rule maps to


@dataclass
class ActCaseResult:
    case: ActCase
    actual: str
    consistent: bool               # actual == expected
    undecided: bool                # actual == cantTell but a decision was expected


def map_outcome(findings: list[dict], *, sc: Optional[str]) -> str:
    """
    Map a scan's findings (for this case) to an ACT outcome. `findings` are the
    scan's finding dicts; only those matching `sc` count. A definite `fail`
    stands alone (any fail → failed); otherwise a needs-review / `cantTell`
    makes the whole case `cantTell`; otherwise `passed`.
    """
    relevant = [f for f in findings if sc is None or (f.get("sc") or {}).get("id") == sc]
    outcomes = {f.get("outcome") for f in relevant}
    if "fail" in outcomes:
        return "failed"
    if "cantTell" in outcomes or any((f.get("provenance") == "needs review") for f in relevant):
        return "cantTell"
    return "passed"


def run_case(case: ActCase, scan_fn: Callable[[str], list[dict]]) -> ActCaseResult:
    actual = map_outcome(scan_fn(case.url), sc=case.sc)
    consistent = actual == case.expected
    undecided = actual == "cantTell" and case.expected in ("passed", "failed", "inapplicable")
    return ActCaseResult(case=case, actual=actual, consistent=consistent, undecided=undecided)


@dataclass
class ActRuleReport:
    rule_id: str
    cases: int = 0
    consistent: int = 0
    undecided: int = 0
    results: list[ActCaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Exact matches over all cases (undecided counted against — honest)."""
        return self.consistent / self.cases if self.cases else float("nan")

    @property
    def decided_pass_rate(self) -> float:
        """Matches over the cases Verity actually decided (undecided excluded)."""
        decided = self.cases - self.undecided
        return self.consistent / decided if decided else float("nan")


@dataclass
class ActReport:
    rules: dict[str, ActRuleReport] = field(default_factory=dict)

    @property
    def totals(self) -> dict:
        cases = sum(r.cases for r in self.rules.values())
        consistent = sum(r.consistent for r in self.rules.values())
        undecided = sum(r.undecided for r in self.rules.values())
        decided = cases - undecided
        return {
            "rules": len(self.rules), "cases": cases,
            "consistent": consistent, "undecided": undecided,
            "pass_rate": consistent / cases if cases else float("nan"),
            "decided_pass_rate": consistent / decided if decided else float("nan"),
        }


def run_act(cases: list[ActCase], scan_fn: Callable[[str], list[dict]]) -> ActReport:
    """Run every case and aggregate per rule."""
    report = ActReport()
    for case in cases:
        res = run_case(case, scan_fn)
        rule = report.rules.setdefault(case.rule_id, ActRuleReport(rule_id=case.rule_id))
        rule.cases += 1
        rule.consistent += int(res.consistent)
        rule.undecided += int(res.undecided)
        rule.results.append(res)
    return report


def load_cases(path: Path) -> list[ActCase]:
    """Load a manifest of ACT cases (JSON list of objects)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [ActCase(rule_id=c["rule_id"], case_id=c["case_id"], url=c["url"],
                    expected=c["expected"], sc=c.get("sc")) for c in data]


def format_report(report: ActReport) -> str:
    """The honest per-rule table (the W15 gate artifact)."""
    t = report.totals
    lines = ["# ACT pass rate", ""]
    lines.append(f"**{t['cases']} cases over {t['rules']} rules**  ·  "
                 f"pass rate **{_pct(t['pass_rate'])}**  ·  "
                 f"decided pass rate {_pct(t['decided_pass_rate'])}  ·  "
                 f"undecided (cantTell) {t['undecided']}")
    lines.append("")
    lines.append("| rule | cases | consistent | undecided | pass rate | decided |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for rid in sorted(report.rules):
        r = report.rules[rid]
        lines.append(f"| {rid} | {r.cases} | {r.consistent} | {r.undecided} | "
                     f"{_pct(r.pass_rate)} | {_pct(r.decided_pass_rate)} |")
    lines.append("")
    lines.append("> `cantTell` is never scored as a pass: undecided cases are counted against the "
                 "headline pass rate and excluded from the decided rate. Both are published.")
    return "\n".join(lines) + "\n"


def _pct(x: float) -> str:
    return "—" if x != x else f"{x:.0%}"
