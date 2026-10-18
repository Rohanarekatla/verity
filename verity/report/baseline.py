"""
A7.2 — baseline storage, content-addressed, with a human-readable diff.

A baseline is a snapshot of the findings a scan produced, stored so a later
scan can be diffed against it. It is what makes Week 8's gate possible — *one
new defect fails the build, not fifty old ones*. A team adopts Verity on a
codebase that already has findings, records them as a baseline, and from then
on only findings absent from the baseline gate. B7.4 (regression keyed to
`ruleset_version` + corpus hash) is the consumer; this module is the store and
the diff it keys on.

Two design commitments, both from the plan's wording:

**Content-addressed.** The baseline's identity (`baseline_id`) is a sha256 over
its *meaningful* content — the version keys plus the sorted set of finding
signatures — not over the file's byte layout. So two baselines with the same
findings have the same id regardless of when they were written or in what
order the scanner happened to emit, and a re-record that changed nothing
produces an identical id (and an empty diff). Timestamps and the human-readable
entry details are deliberately *excluded* from the id, or every re-record would
look like a change.

**Human-readable.** The stored file is pretty-printed JSON and every signature
carries its sc / rule / selector / severity alongside the hash, so a reviewer
reading a baseline update in a PR diff (A8.3) can see *what* is being accepted,
not just that 64 hex characters changed. The diff itself renders as plain text:
new, fixed, unchanged.

**Versioned, loudly.** The baseline records `validator_version`. The finding
signature scheme is pinned to that version (A7.1 was a MAJOR bump precisely
because it changed the scheme). Diffing a baseline against a scan from a
different validator major is not a silent mismatch — `diff_report` flags it,
because every signature would spuriously read as "new/fixed" and the gate would
be nonsense.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from verity.agents.validator import VALIDATOR_VERSION, signature_for
from verity.models.schemas import AuditReport, Finding

# Baselines live alongside the content-addressed render cache, under the
# project's `.verity/` directory. The committed "current" baseline is a path
# the user chooses (A8.3 proposes updates to it); the store here is the
# content-addressed archive.
DEFAULT_BASELINE_DIR = Path(".verity") / "baselines"


class BaselineEntry(BaseModel):
    """One baselined finding: the signature, plus enough context for a human
    reading the file to know what was accepted without resolving the hash."""

    signature: str = Field(min_length=64, max_length=64)
    sc_id: str
    rule_id: str
    selector: Optional[str] = None
    severity: str
    provenance: str


class Baseline(BaseModel):
    """A recorded set of accepted findings for one target."""

    verity_version: str
    ruleset_version: str
    validator_version: str
    standard: str
    target: str
    created: str  # ISO-8601 UTC; excluded from baseline_id
    baseline_id: str  # sha256 over version keys + sorted signatures
    entries: list[BaselineEntry] = []

    @property
    def signatures(self) -> set[str]:
        return {e.signature for e in self.entries}


def _baseline_id(validator_version: str, ruleset_version: str, signatures: list[str]) -> str:
    """
    Content address: sha256 over the version keys and the *sorted* signature
    set. Order-independent and timestamp-independent, so an unchanged re-record
    hashes identically. The version keys are in the hash because the same
    signatures under a different scheme are not the same baseline.
    """
    canonical = json.dumps(
        {
            "validator_version": validator_version,
            "ruleset_version": ruleset_version,
            "signatures": sorted(signatures),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_baseline(report: AuditReport, *, created: Optional[datetime] = None) -> Baseline:
    """
    Snapshot a report's findings as a baseline.

    Waived findings are excluded: a waiver is already an accepted, justified
    failure, and baselining it too would record the same acceptance twice and
    make a lapsed waiver (which should re-gate) look baselined instead.
    """
    entries: list[BaselineEntry] = []
    seen: set[str] = set()
    for f in report.findings:
        if getattr(f, "waived", False):
            continue
        sig = signature_for(f)
        if sig in seen:
            continue
        seen.add(sig)
        entries.append(
            BaselineEntry(
                signature=sig,
                sc_id=f.sc.id,
                rule_id=f.rule_id,
                selector=f.evidence.dom_selector,
                severity=f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                provenance=f.provenance.value if hasattr(f.provenance, "value") else str(f.provenance),
            )
        )

    entries.sort(key=lambda e: e.signature)
    created_dt = created or datetime.now(timezone.utc)
    return Baseline(
        verity_version=report.verity_version,
        ruleset_version=report.ruleset_version,
        validator_version=VALIDATOR_VERSION,
        standard=report.standard,
        target=report.target,
        created=created_dt.isoformat(),
        baseline_id=_baseline_id(VALIDATOR_VERSION, report.ruleset_version, [e.signature for e in entries]),
        entries=entries,
    )


def write_baseline(baseline: Baseline, path: Path) -> None:
    """Write a baseline as pretty JSON (human-readable, reviewable in a PR)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline.model_dump(), indent=2) + "\n", encoding="utf-8")


def store_baseline(baseline: Baseline, root: Path = DEFAULT_BASELINE_DIR) -> Path:
    """Archive a baseline content-addressed: `.verity/baselines/<id>.json`."""
    path = root / f"{baseline.baseline_id}.json"
    write_baseline(baseline, path)
    return path


def load_baseline(path: Path) -> Baseline:
    """Load and validate a baseline, re-checking its content address.

    A baseline whose stored `baseline_id` does not match its contents has been
    hand-edited or corrupted; that is raised rather than trusted, because the
    gate downstream decides what fails a build from this file.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    baseline = Baseline.model_validate(data)
    recomputed = _baseline_id(
        baseline.validator_version,
        baseline.ruleset_version,
        [e.signature for e in baseline.entries],
    )
    if recomputed != baseline.baseline_id:
        raise ValueError(
            f"{path.name}: baseline_id does not match contents "
            f"(stored {baseline.baseline_id[:12]}…, computed {recomputed[:12]}…); "
            "the file was edited by hand or is corrupt"
        )
    return baseline


@dataclass
class BaselineDiff:
    """The result of comparing a scan to a baseline."""

    new: list[Finding]            # in the scan, not in the baseline — these gate
    fixed: list[str]              # in the baseline, gone from the scan (signatures)
    unchanged: list[Finding]      # in both
    version_mismatch: Optional[str] = None  # set when schemes differ; diff is unreliable

    @property
    def is_regression(self) -> bool:
        """A regression is any new, non-baselined finding. This is the signal
        Week 8's gate turns into a build failure."""
        return len(self.new) > 0


def diff_report(baseline: Baseline, report: AuditReport) -> BaselineDiff:
    """
    Diff a fresh report against a baseline.

    `new` is what gates: a finding whose signature is not in the baseline.
    `fixed` is recorded, not gated — a baselined finding that is gone is good
    news a reader wants to see (and a prompt to re-record the baseline).

    If the report was produced under a different validator major than the
    baseline, the signature schemes are incompatible and every signature would
    read as new/fixed. Rather than emit a nonsense diff, that is flagged in
    `version_mismatch`; the caller (and the gate) must treat the result as
    unreliable and prompt a baseline re-record.
    """
    mismatch: Optional[str] = None
    base_major = baseline.validator_version.split(".")[0]
    cur_major = VALIDATOR_VERSION.split(".")[0]
    if base_major != cur_major:
        mismatch = (
            f"baseline was recorded under validator {baseline.validator_version}, "
            f"this scan is {VALIDATOR_VERSION}; the signature scheme changed, so "
            "the baseline must be re-recorded before its diff can be trusted"
        )

    base_sigs = baseline.signatures
    new: list[Finding] = []
    unchanged: list[Finding] = []
    seen: set[str] = set()
    scan_sigs: set[str] = set()
    for f in report.findings:
        if getattr(f, "waived", False):
            continue
        sig = signature_for(f)
        scan_sigs.add(sig)
        if sig in seen:
            continue
        seen.add(sig)
        (unchanged if sig in base_sigs else new).append(f)

    fixed = sorted(base_sigs - scan_sigs)
    return BaselineDiff(new=new, fixed=fixed, unchanged=unchanged, version_mismatch=mismatch)


def format_diff(diff: BaselineDiff) -> str:
    """Render a baseline diff as plain text for a terminal or a PR comment."""
    lines: list[str] = []
    if diff.version_mismatch:
        lines.append(f"⚠ {diff.version_mismatch}")
        lines.append("")

    lines.append(
        f"Baseline diff: {len(diff.new)} new, {len(diff.fixed)} fixed, "
        f"{len(diff.unchanged)} unchanged."
    )

    if diff.new:
        lines.append("")
        lines.append(f"NEW ({len(diff.new)}) — these gate the build:")
        for f in diff.new:
            sel = f.evidence.dom_selector or "—"
            lines.append(f"  + {f.sc.id}  {f.rule_id}  {sel}")

    if diff.fixed:
        lines.append("")
        lines.append(f"FIXED ({len(diff.fixed)}) — gone since the baseline:")
        for sig in diff.fixed:
            lines.append(f"  - {sig[:12]}…")

    return "\n".join(lines)
