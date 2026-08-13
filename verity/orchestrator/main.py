"""
verity/orchestrator/main.py
Main orchestrator pipeline for single-URL accessibility scanning.
"""

import logging
from pathlib import Path
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


def extract_sc_id(tags: Any) -> Optional[str]:
    """
    Derive a WCAG success-criterion id from axe's tag list, or None.

    axe tags the criterion as `wcag<digits>` — `wcag143` means SC 1.4.3.
    Level tags (`wcag2a`, `wcag2aa`, `wcag22aa`) and category tags
    (`cat.color`, `best-practice`, `ACT`, `EN-301-549`) are not criterion
    references and must not be parsed as one.

    Returning None is meaningful: axe rules tagged `best-practice` — such as
    `region` and `landmark-one-main` — map to no success criterion at all.
    They are real findings, but they are not WCAG conformance failures, and
    reporting them as such would be a false positive.
    """
    if not isinstance(tags, list):
        return None
    for tag in tags:
        if not isinstance(tag, str) or not tag.startswith("wcag"):
            continue
        digits = tag[4:]
        # Level tags carry a trailing a/aa/aaa; criterion tags are digits only.
        if not digits.isdigit():
            continue
        # SC ids are three parts, one digit each in WCAG 2.x (e.g. 1.4.3).
        if len(digits) == 3:
            return f"{digits[0]}.{digits[1]}.{digits[2]}"
    return None


def map_raw_violation_to_finding(raw: dict[str, Any], page_state_hash: str) -> Finding:
    """
    Transforms a raw violation node dictionary (from Node axe-core worker)
    into a strictly validated Pydantic Finding object.
    
    Axe node output shape:
    {id, impact, tags, description, help, helpUrl, selector, html, failureSummary}
    """
    rule_id = raw.get("id", "unknown-rule")
    sc_name = raw.get("help", "Accessibility violation")

    sc_id = extract_sc_id(raw.get("tags", []))
    if sc_id is None:
        # Callers must filter these out before mapping. Guessing an SC here
        # would emit an authoritative WCAG failure for a rule that maps to no
        # success criterion at all — a false positive, which is the one
        # failure mode this product cannot afford.
        raise ValueError(
            f"rule '{rule_id}' carries no WCAG success-criterion tag; "
            "it must not be mapped to a Finding"
        )

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
        # Resolved from this file's location, not the caller's cwd — the CLI
        # must work from any directory. The built entry point is
        # dist/rpc/server.js (mirroring node-worker/rpc/server.ts); there is
        # no dist/index.js.
        worker = (
            Path(__file__).resolve().parents[2]
            / "node-worker" / "dist" / "rpc" / "server.js"
        )
        if not worker.exists():
            raise FileNotFoundError(
                f"Node worker not built: {worker} is missing. "
                "Run: cd node-worker && npm install && npm run build"
            )
        node_worker_command = ["node", str(worker)]

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
        #
        # Rules carrying no WCAG success-criterion tag (axe's `best-practice`
        # set, e.g. `region`, `landmark-one-main`) are excluded from the WCAG
        # conformance report — they are genuine findings but not conformance
        # failures, and emitting them as authoritative would be a false
        # positive. They are counted and logged, never silently dropped.
        #
        # OPEN DECISION (for an ADR): should best-practice findings be
        # reported in a separate, non-gating section rather than omitted?
        findings: list[Finding] = []
        non_wcag: list[str] = []
        for raw_v in raw_violations:
            if not isinstance(raw_v, dict):
                continue
            if extract_sc_id(raw_v.get("tags", [])) is None:
                non_wcag.append(raw_v.get("id", "unknown-rule"))
                continue
            findings.append(
                map_raw_violation_to_finding(raw_v, page_state_hash=content_hash)
            )

        if non_wcag:
            logger.info(
                "Excluded %d non-WCAG (best-practice) finding(s) from the "
                "conformance report: %s",
                len(non_wcag),
                ", ".join(sorted(set(non_wcag))),
            )

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