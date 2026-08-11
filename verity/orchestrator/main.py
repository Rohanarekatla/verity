"""
verity/orchestrator/main.py
Main orchestrator pipeline for single-URL accessibility scanning.
"""

import logging
from typing import Optional, Any

from verity.models.schemas import (
    AuditReport,
    Finding,
    SuccessCriterion,
    Evidence,
    Confidence,
    Level,
    Severity,
    Provenance,
    Modality,
)
from verity.orchestrator.rpc_client import RPCClient

logger = logging.getLogger(__name__)


def map_raw_violation_to_finding(raw: dict[str, Any], page_state_hash: str) -> Finding:
    """
    Transforms a raw violation dictionary (from Developer A's axe-core worker)
    into a strictly validated Pydantic Finding object.
    """
    rule_id = raw.get("id", "unknown-rule")
    sc_id = raw.get("wcag_id", "1.1.1")
    sc_name = raw.get("help", "Accessibility violation")

    success_criterion = SuccessCriterion(
        id=sc_id,
        name=sc_name,
        level=Level.AA,
        modality=Modality.DETERMINISTIC,
    )

    evidence = Evidence(
        dom_selector=raw.get("selector"),
        computed_values=raw.get("details", {}) if isinstance(raw.get("details"), dict) else {},
    )

    confidence = Confidence(
        score=1.0,
        method="deterministic",
    )

    raw_impact = str(raw.get("impact", "moderate")).lower()
    try:
        severity = Severity(raw_impact)
    except ValueError:
        logger.warning(f"Unknown severity impact '{raw_impact}' for rule '{rule_id}'. Defaulting to MODERATE.")
        severity = Severity.MODERATE

    selector_hash = hash(str(raw.get("selector", ""))) & 0xFFFF

    return Finding(
        id=f"{rule_id}-{selector_hash:04x}",
        sc=success_criterion,
        provenance=Provenance.AUTHORITATIVE,  # axe-core rules are 100% deterministic
        severity=severity,
        confidence=confidence,
        agent="axe-core",
        engine="node-worker",
        outcome="fail",
        message=raw.get("description", "Rule violation detected"),
        evidence=evidence,
        page_state_hash=page_state_hash,
    )


async def scan_url(
    url: str,
    node_worker_command: Optional[list[str]] = None,
    timeout: float = 30.0,
) -> AuditReport:
    """
    Main orchestrator entry point to run a full accessibility scan on a single URL.
    Coordinates worker process lifecycle, requests render/analysis artifacts, and returns
    an AuditReport.
    """
    if not url:
        raise ValueError("Target URL must be provided.")

    if node_worker_command is None:
        node_worker_command = ["node", "node-worker/dist/index.js"]

    client = RPCClient(command=node_worker_command, default_timeout=timeout)

    try:
        await client.start()

        # Step 1: Request Page Render from Developer A's worker
        logger.info(f"Requesting render for: {url}")
        render_result = await client.send_request("render", {"url": url})
        content_hash = render_result.get("content_hash", "default_hash")

        # Step 2: Request Accessibility Analysis from Developer A's worker
        logger.info(f"Requesting analysis for: {url}")
        analysis_result = await client.send_request("analyze", {"url": url})
        raw_violations = analysis_result.get("violations", [])

        # Step 3: Map Raw Violations to Validated Findings
        findings: list[Finding] = []
        for raw_v in raw_violations:
            if isinstance(raw_v, dict):
                finding = map_raw_violation_to_finding(raw_v, page_state_hash=content_hash)
                findings.append(finding)

        # Step 4: Build Conformance Map
        conformance_map = {f.sc.id: f.outcome for f in findings}

        # Step 5: Return Final Audit Report
        return AuditReport(
            target=url,
            standard="WCAG2.2-AA",
            findings=findings,
            conformance=conformance_map,
            verity_version="0.1.0",
            ruleset_version="1.0.0",
        )

    finally:
        # Guaranteed process cleanup
        await client.stop()