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
    Transforms a raw violation node dictionary (from Node axe-core worker)
    into a strictly validated Pydantic Finding object.
    
    Axe node output shape:
    {id, impact, tags, description, help, helpUrl, selector, html, failureSummary}
    """
    rule_id = raw.get("id", "unknown-rule")
    sc_name = raw.get("help", "Accessibility violation")

    # Map tags to WCAG SC ID if present, otherwise default
    sc_id = "1.1.1"
    tags = raw.get("tags", [])
    if isinstance(tags, list):
        for tag in tags:
            if tag.startswith("wcag") and len(tag) >= 7:
                # e.g., 'wcag111' -> '1.1.1' or 'wcag143' -> '1.4.3'
                digits = tag.replace("wcag", "").replace("a", "").replace("aa", "").replace("aaa", "")
                if len(digits) == 3:
                    sc_id = f"{digits[0]}.{digits[1]}.{digits[2]}"
                    break

    success_criterion = SuccessCriterion(
        id=sc_id,
        name=sc_name,
        level=Level.AA,
        modality=Modality.DETERMINISTIC,
    )

    # Build evidence dictionary from raw axe node details
    computed_details = {
        "description": raw.get("description", ""),
        "helpUrl": raw.get("helpUrl", ""),
        "failureSummary": raw.get("failureSummary", ""),
        "html": raw.get("html", ""),
    }

    evidence = Evidence(
        dom_selector=raw.get("selector"),
        computed_values=computed_details,
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

    selector_str = str(raw.get("selector", ""))
    selector_hash = hash(selector_str) & 0xFFFF

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

        # Step 1: Request Page Render from Node worker
        logger.info(f"Requesting render for: {url}")
        # Support both .call() and .send_request() depending on RPCClient method name
        rpc_call = getattr(client, "call", client.send_request)
        render_result = await rpc_call("render", {"url": url})

        # Extract artifactId and nested content_hash under page_state
        artifact_id = render_result.get("artifactId")
        if not artifact_id:
            raise ValueError("Node worker render response missing required 'artifactId' field.")

        page_state = render_result.get("page_state", {})
        content_hash = page_state.get("content_hash", "default_hash") if isinstance(page_state, dict) else "default_hash"

        # Step 2: Request Accessibility Analysis using 'runAxe' and artifactId
        logger.info(f"Requesting runAxe analysis for artifact: {artifact_id}")
        analysis_result = await rpc_call("runAxe", {"artifactId": artifact_id})
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