"""
verity/report/sarif.py — SARIF 2.1.0 output (B8.1, B8.2).

Written against `docs/sarif-reference.md`, which was hand-built from the spec
*before* this file existed, per the Week 8 artifact rule. Read that first if
anything here looks arbitrary — it records which fields GitHub actually needs
and what breaks without each one.

The two decisions that matter:

**Level comes from provenance, not severity (B8.1).** `authoritative` →
`error`, `ai assisted` → `warning`, `needs review` → `note`. SARIF `level` is
what decides whether CI goes red, so it must track *how much we trust the
finding*, not how bad the defect would be if real. A `critical`-severity
needs-review finding is still a `note`. Severity lives in `properties`, where
it informs a human without gating a build.

**`partialFingerprints` is how GitHub tells "same alert" from "new alert"
(B8.2).** Without it every alert looks new on every run, "fixed" is never
detected, and the same defect re-notifies forever. Ours is keyed on the dedup
signature under `verityFindingSignature/v1` — versioned, because A7.1's
stable-signature work will change the scheme and GitHub must not silently
merge two incompatible fingerprints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from verity.agents.validator import signature_for
from verity.models.schemas import AuditReport, Finding, Provenance
from verity.report.policy import DEFAULT_POLICY, CiPolicy

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

TOOL_NAME = "Verity"
TOOL_URI = "https://github.com/Rohanarekatla/verity"

# B8.1 — the mapping the plan specifies.
_LEVEL_BY_PROVENANCE: dict[Provenance, str] = {
    Provenance.AUTHORITATIVE: "error",
    Provenance.AI_ASSISTED: "warning",
    Provenance.NEEDS_REVIEW: "note",
}

# Key name carries a version. When A7.1 lands and the signature scheme
# changes, this becomes `/v2` and GitHub treats the alerts as new rather than
# silently matching fingerprints computed two different ways.
FINGERPRINT_KEY = "verityFindingSignature/v1"

_WCAG_UNDERSTANDING = (
    "https://www.w3.org/WAI/WCAG22/Understanding/"
)


def sarif_level(finding: Finding) -> str:
    """Provenance → SARIF level. See the module docstring for why not severity."""
    return _LEVEL_BY_PROVENANCE.get(finding.provenance, "note")


def repo_relative_path(target: str, repo_root: Optional[Path] = None) -> Optional[str]:
    """
    Turn a scan target into a repo-relative path, or None if it isn't one.

    This is the limitation `docs/sarif-reference.md` §5 surfaced: **Verity
    scans a URL, SARIF annotates a file.** An inline PR annotation needs a
    repo-relative path; `https://staging.example.com/pricing` has none, and a
    DOM selector is not a file position.

    So:
    - a `file://` URL inside the repo → the relative path, and annotations work
    - anything else → None, and the result is emitted without a
      `physicalLocation`, appearing in the Security tab with the selector in
      the message

    Returning None rather than inventing a path is deliberate. A wrong `uri`
    uploads successfully and then annotates the wrong line of the wrong file,
    which is worse than no annotation at all.
    """
    parsed = urlparse(target)
    if parsed.scheme not in ("file", ""):
        return None

    raw = unquote(parsed.path or target)
    # Windows file URLs arrive as /C:/Users/... — strip the leading slash.
    if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]

    try:
        candidate = Path(raw).resolve()
    except (OSError, ValueError):
        return None

    root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        # Outside the repo: a real file, but not one a PR can annotate.
        return None


def _rule_for(finding: Finding) -> dict[str, Any]:
    """One SARIF `reportingDescriptor` (a rule) for this finding's rule id."""
    sc = finding.sc
    return {
        "id": finding.rule_id,
        "name": "".join(part.capitalize() for part in finding.rule_id.split("-")),
        "shortDescription": {"text": f"SC {sc.id} — {sc.name}"},
        "fullDescription": {
            "text": (
                f"WCAG 2.2 success criterion {sc.id} ({sc.name}), "
                f"level {sc.level.value}."
            )
        },
        "helpUri": f"{_WCAG_UNDERSTANDING}{sc.name.lower().replace(' ', '-').replace('(', '').replace(')', '')}.html",
        "defaultConfiguration": {"level": sarif_level(finding)},
        "properties": {
            "tags": [
                "accessibility",
                "wcag",
                f"wcag{sc.id.replace('.', '')}",
                f"level-{sc.level.value.lower()}",
            ],
            "verity.successCriterion": sc.id,
            "verity.wcagLevel": sc.level.value,
            "verity.modality": sc.modality.value,
        },
    }


def _location_for(
    finding: Finding, target_path: Optional[str]
) -> list[dict[str, Any]]:
    """
    The `locations` array, or empty when we have no file to point at.

    `startLine: 1` with an explicit note rather than a guessed line: the
    rendered DOM a selector refers to may come from a template, a component
    or a CMS record, and URL→source mapping is not in scope this week.
    Pointing at line 1 is honest and lands the annotation on the right file.
    """
    if target_path is None:
        return []

    return [
        {
            "physicalLocation": {
                "artifactLocation": {"uri": target_path},
                "region": {"startLine": 1, "startColumn": 1},
            },
            "logicalLocations": [
                {
                    "name": finding.evidence.dom_selector or "(no selector)",
                    "kind": "element",
                }
            ],
        }
    ]


def _result_for(
    finding: Finding,
    rule_index: int,
    target_path: Optional[str],
    target: str,
) -> dict[str, Any]:
    message = finding.message
    selector = finding.evidence.dom_selector
    if selector:
        message = f"{message} (element: {selector})"
    if target_path is None:
        # No inline annotation possible — put the page in the text so the
        # Security-tab entry is still actionable.
        message = f"{message} [{target}]"

    result: dict[str, Any] = {
        "ruleId": finding.rule_id,
        "ruleIndex": rule_index,
        "level": sarif_level(finding),
        "message": {"text": message},
        "locations": _location_for(finding, target_path),
        # B8.2 — alert identity across commits.
        "partialFingerprints": {FINGERPRINT_KEY: signature_for(finding)},
        "properties": {
            "verity.severity": finding.severity.value,
            "verity.provenance": finding.provenance.value,
            "verity.outcome": finding.outcome,
            "verity.successCriterion": finding.sc.id,
            "verity.wcagLevel": finding.sc.level.value,
            "verity.agent": finding.agent,
            "verity.confidence": finding.confidence.score,
            "verity.confidenceMethod": finding.confidence.method,
            "verity.waived": finding.waived,
            "verity.findingId": finding.id,
        },
    }

    if finding.confidence.model:
        result["properties"]["verity.model"] = finding.confidence.model

    # A waived finding is retained in the report (B7.2) but must be visually
    # distinct and must never gate. `suppressions` is the SARIF-native way to
    # say "accepted", and GitHub renders it as dismissed rather than open.
    if finding.waived:
        waiver = finding.evidence.computed_values.get("waiver", {})
        result["suppressions"] = [
            {
                "kind": "external",
                "status": "accepted",
                "justification": waiver.get("justification", "waived"),
            }
        ]

    if finding.remediation:
        result["fixes"] = [{"description": {"text": finding.remediation}}]

    return result


def build_sarif(
    report: AuditReport,
    policy: CiPolicy = DEFAULT_POLICY,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Turn an `AuditReport` into a SARIF 2.1.0 document.

    `policy.annotate_on` decides what is included (B8.4) — by default
    authoritative and AI-assisted findings, with needs-review omitted unless
    the policy asks for everything. Note this is *annotate*, not *fail*: a
    finding appearing here does not gate.
    """
    target_path = repo_relative_path(report.target, repo_root)
    findings = policy.annotated_findings(report.findings)

    # Rules are deduplicated by id and referenced by index, which is what the
    # spec wants and what keeps a 300-finding report from repeating the same
    # rule description 300 times.
    rule_indices: dict[str, int] = {}
    rules: list[dict[str, Any]] = []
    for finding in findings:
        if finding.rule_id not in rule_indices:
            rule_indices[finding.rule_id] = len(rules)
            rules.append(_rule_for(finding))

    results = [
        _result_for(f, rule_indices[f.rule_id], target_path, report.target)
        for f in findings
    ]

    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": TOOL_NAME,
                "version": report.verity_version,
                "informationUri": TOOL_URI,
                "rules": rules,
            }
        },
        "results": results,
        "properties": {
            "verity.target": report.target,
            "verity.standard": report.standard,
            "verity.rulesetVersion": report.ruleset_version,
            "verity.policy": policy.describe(),
            "verity.inlineAnnotationsPossible": target_path is not None,
        },
    }

    if report.latency is not None:
        run["properties"]["verity.latencySeconds"] = report.latency.total_seconds

    if target_path is None:
        # Say so in the document rather than leaving someone to wonder why no
        # annotation appeared. See docs/sarif-reference.md §5.
        run["properties"]["verity.noInlineAnnotationReason"] = (
            f"target {report.target!r} is not a file inside the repository; "
            "results appear in the Security tab without inline annotations"
        )

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [run],
    }


def write_sarif(
    report: AuditReport,
    path: Path | str,
    policy: CiPolicy = DEFAULT_POLICY,
    repo_root: Optional[Path] = None,
) -> Path:
    """Serialise the SARIF document to disk and return where it went."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    document = build_sarif(report, policy=policy, repo_root=repo_root)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return out
