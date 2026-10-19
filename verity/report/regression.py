"""
B7.4 — regression gating against a baseline, keyed to `ruleset_version` +
corpus hash.

Week 7's gate: *on a page with 50 pre-existing findings, introducing one new
defect fails the build on exactly that one.* Week 8's: *build fails only on
**new authoritative** findings.* Rohan's A7.2 (`verity.report.baseline`) is
the store and the diff; this module is the decision the CLI makes with it.

**What the key means.** A regression is "a finding that is not in the accepted
set". That statement is only meaningful when both sides were judged by the
same rules and identified by the same scheme, so the regression is keyed to:

- `ruleset_version` — the rules that produced the findings. A ruleset bump
  (new axe rules, a new agent) adds findings the developer did not introduce;
  calling those "regressions" would fail a PR for something nobody in it did.
- the **corpus hash** — the baseline's content address (`baseline_id`), a
  sha256 over the accepted finding signatures plus the version keys. It names
  *exactly* which accepted set a verdict was computed against, so a CI log
  line can be traced back to the baseline file that produced it.
- the validator major (signature scheme) — already checked by `diff_report`.

**Mismatch is refused, not guessed.** If the ruleset or the signature scheme
differs, every signature reads as new or fixed and the diff is noise. Gating
on it would either fail the build on 50 old findings (the exact uninstall
scenario Week 7 exists to prevent) or pass it by ignoring them. Neither is a
verdict, so it raises `BaselineIncompatible` and the CLI exits 2 — the same
doctrine as a broken waiver file: our config, not the page, is the problem.
The fix is to re-record the baseline (A8.3's workflow proposes that in a PR).

**The target is deliberately not part of the key.** A local file scanned on a
laptop and in CI resolves to different `file://` URIs, so a strict target
check would break the main use case. A different target is logged as a
warning instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from verity.models.schemas import AuditReport, Finding
from verity.report.baseline import Baseline, BaselineDiff, diff_report, load_baseline
from verity.report.policy import CiPolicy

logger = logging.getLogger(__name__)


class BaselineIncompatible(Exception):
    """The baseline cannot be diffed against this scan; re-record it."""


@dataclass(frozen=True)
class RegressionKey:
    """What a regression verdict was computed against."""

    ruleset_version: str
    corpus_hash: str  # the baseline's content address (baseline_id)

    def describe(self) -> str:
        return f"ruleset {self.ruleset_version}, baseline {self.corpus_hash[:12]}…"


@dataclass
class RegressionResult:
    key: RegressionKey
    diff: BaselineDiff
    gating: list[Finding]  # new findings the policy says fail the build


def open_baseline(path: Optional[str | Path]) -> Optional[Baseline]:
    """
    Load the baseline up front, before the render. A missing or hand-edited
    baseline is a config error and should fail in a second, not after a
    two-minute scan. `None` means no baseline: gate on every finding, as
    before B7.4.
    """
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise BaselineIncompatible(
            f"baseline file {p} does not exist; record one with --write-baseline"
        )
    return load_baseline(p)  # raises ValueError on a tampered content address


def check_compatible(baseline: Baseline, report: AuditReport) -> RegressionKey:
    """Raise if the baseline and the scan are not comparable; else the key."""
    if baseline.ruleset_version != report.ruleset_version:
        raise BaselineIncompatible(
            f"baseline was recorded under ruleset {baseline.ruleset_version}, "
            f"this scan is ruleset {report.ruleset_version}; findings from new "
            "rules are not regressions anyone introduced, so the baseline must "
            "be re-recorded before it can gate"
        )
    if baseline.target != report.target:
        logger.warning(
            "Baseline target %s differs from scan target %s; diffing anyway "
            "(local file paths differ between machines).",
            baseline.target, report.target,
        )
    return RegressionKey(
        ruleset_version=report.ruleset_version, corpus_hash=baseline.baseline_id
    )


def gate_against_baseline(
    baseline: Baseline, report: AuditReport, policy: CiPolicy
) -> RegressionResult:
    """
    Only findings absent from the baseline can gate, and of those only the
    ones the CI policy gates on (default: authoritative). Baselined findings
    stay in the report and the SARIF — they are accepted, not hidden.
    """
    key = check_compatible(baseline, report)
    diff = diff_report(baseline, report)
    if diff.version_mismatch:
        raise BaselineIncompatible(diff.version_mismatch)
    return RegressionResult(key=key, diff=diff, gating=policy.gating_findings(diff.new))
