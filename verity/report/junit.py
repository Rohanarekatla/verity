"""
verity/report/junit.py — JUnit XML output (B8.3).

SARIF is the good format, but GitHub code scanning is the only thing that
reads it well. JUnit XML is read by Jenkins, GitLab, CircleCI, Azure
Pipelines, Buildkite and every test reporter written in the last twenty
years. For a team not on GitHub Actions, this is the only way Verity's
findings show up anywhere other than stdout.

The mapping is not obvious, because JUnit was designed for tests and has two
different "this didn't pass" states:

| Verity | JUnit | Why |
|---|---|---|
| gating finding | `<failure>` | the build should be red |
| annotated, non-gating | `<skipped>` | reported, visibly not a pass, does not fail |
| waived | `<skipped>` | accepted; the justification goes in the message |
| pass | bare `<testcase>` | counted, silent |

Using `<skipped>` for non-gating findings is the useful trick: every JUnit
reader renders skips distinctly from both passes and failures, and none of
them fails a build on one. An `<error>` would go red, and swallowing them
entirely would hide needs-review findings from anyone not reading SARIF.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from verity.models.schemas import AuditReport, Finding
from verity.report.policy import DEFAULT_POLICY, CiPolicy


def _classname(finding: Finding) -> str:
    """
    Group findings by success criterion.

    Most JUnit UIs show a tree keyed on classname, so `wcag.1.4.3` puts every
    contrast finding together — which is how someone triaging actually wants
    to read them.
    """
    return f"wcag.{finding.sc.id}"


def _name(finding: Finding) -> str:
    selector = finding.evidence.dom_selector or "(no selector)"
    return f"{finding.rule_id} @ {selector}"


def _detail(finding: Finding) -> str:
    """Everything a reader needs without opening the JSON report."""
    lines = [
        finding.message,
        "",
        f"success criterion : {finding.sc.id} ({finding.sc.name}), level {finding.sc.level.value}",
        f"severity          : {finding.severity.value}",
        f"provenance        : {finding.provenance.value}",
        f"outcome           : {finding.outcome}",
        f"confidence        : {finding.confidence.score} ({finding.confidence.method})",
        f"agent             : {finding.agent}",
        f"selector          : {finding.evidence.dom_selector or '(none)'}",
        f"finding id        : {finding.id}",
    ]
    if finding.confidence.model:
        lines.append(f"model             : {finding.confidence.model}")

    adjudication = finding.evidence.computed_values.get("contrast_adjudication")
    if isinstance(adjudication, dict) and "worst_case_ratio" in adjudication:
        lines.append(f"worst-case ratio  : {adjudication['worst_case_ratio']}")

    lapsed = finding.evidence.computed_values.get("waiver_expired")
    if isinstance(lapsed, dict):
        lines.append(
            f"NOTE              : a waiver for this finding expired on "
            f"{lapsed.get('expired_on')} — it is no longer suppressed"
        )

    if finding.remediation:
        lines += ["", f"remediation       : {finding.remediation}"]

    return "\n".join(lines)


def build_junit(
    report: AuditReport, policy: CiPolicy = DEFAULT_POLICY
) -> ET.ElementTree:
    """
    Build a JUnit XML tree from an audit report.

    One `<testcase>` per annotated finding. `failures` counts only gating
    findings, so a CI system that fails on a non-zero failure count agrees
    with `verity scan`'s own exit code rather than contradicting it — two
    different answers to "did this pass" is worse than either answer alone.
    """
    findings = policy.annotated_findings(report.findings)
    gating = {id(f) for f in policy.gating_findings(report.findings)}

    failures = 0
    skipped = 0

    suite = ET.Element(
        "testsuite",
        {
            "name": "verity",
            "tests": str(len(findings)),
            "hostname": report.target,
            "timestamp": "",
        },
    )

    props = ET.SubElement(suite, "properties")
    for key, value in [
        ("verity.target", report.target),
        ("verity.standard", report.standard),
        ("verity.version", report.verity_version),
        ("verity.rulesetVersion", report.ruleset_version),
        ("verity.policy", policy.describe()),
    ]:
        ET.SubElement(props, "property", {"name": key, "value": str(value)})

    if report.latency is not None:
        ET.SubElement(
            props,
            "property",
            {"name": "verity.latencySeconds", "value": str(report.latency.total_seconds)},
        )

    for finding in findings:
        case = ET.SubElement(
            suite,
            "testcase",
            {"classname": _classname(finding), "name": _name(finding), "time": "0"},
        )

        if id(finding) in gating:
            failures += 1
            failure = ET.SubElement(
                case,
                "failure",
                {
                    "type": f"wcag-{finding.sc.id}",
                    "message": f"[{finding.severity.value}] {finding.message}"[:200],
                },
            )
            failure.text = _detail(finding)

        elif finding.waived:
            skipped += 1
            waiver = finding.evidence.computed_values.get("waiver", {})
            skip = ET.SubElement(
                case,
                "skipped",
                {
                    "message": (
                        f"waived by {waiver.get('approved_by', 'unknown')} "
                        f"until {waiver.get('expires', 'unknown')}"
                    )[:200]
                },
            )
            skip.text = (
                f"{_detail(finding)}\n\n"
                f"waiver justification: {waiver.get('justification', '(none)')}"
            )

        elif finding.outcome == "pass":
            # A bare testcase: counted, silent. Lets a reader tell "checked
            # and fine" from "never checked".
            pass

        else:
            skipped += 1
            skip = ET.SubElement(
                case,
                "skipped",
                {
                    "message": (
                        f"{finding.provenance.value}: reported, does not gate "
                        f"({finding.outcome})"
                    )[:200]
                },
            )
            skip.text = _detail(finding)

    suite.set("failures", str(failures))
    suite.set("errors", "0")
    suite.set("skipped", str(skipped))

    suites = ET.Element(
        "testsuites",
        {
            "name": "verity",
            "tests": str(len(findings)),
            "failures": str(failures),
            "errors": "0",
        },
    )
    suites.append(suite)
    return ET.ElementTree(suites)


def write_junit(
    report: AuditReport,
    path: Path | str,
    policy: CiPolicy = DEFAULT_POLICY,
) -> Path:
    """Serialise the JUnit XML to disk and return where it went."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tree = build_junit(report, policy=policy)
    ET.indent(tree, space="  ")
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out
