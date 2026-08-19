"""
verity/orchestrator/main.py
Main orchestrator pipeline for single-URL accessibility scanning.
"""

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional, Any

from verity.agents.contrast import flag_needs_review
from verity.agents.validator import process_findings
from verity.models.schemas import (
    AuditReport,
    Finding,
    Latency,
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

# Outcome precedence when several findings land on the same success
# criterion. A criterion that failed anywhere has failed, and a definite
# failure is not softened by an undecided sibling — `color-contrast` emits
# into both the `violations` and `incomplete` buckets and both map to
# SC 1.4.3, so this collision is the common case, not an edge case.
_OUTCOME_RANK = {"pass": 0, "cantTell": 1, "fail": 2}


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


def derive_finding_id(rule_id: str, selector: str) -> str:
    """
    A finding id that is the same on every run of an unchanged page.

    Deliberately *not* `hash()`: CPython salts string hashing per process
    (PEP 456), so `hash("#btn")` differs between runs unless PYTHONHASHSEED
    is pinned. Ids built that way churn on every scan, which makes report
    diffing, baselining (Week 7) and any cross-run reference meaningless —
    and it fails silently, because each individual report looks fine.

    12 hex characters is 48 bits: collision-free in practice for a single
    page, against the ~16 bits the previous `& 0xFFFF` mask left.
    """
    digest = hashlib.sha256(f"{rule_id}|{selector}".encode("utf-8")).hexdigest()
    return f"{rule_id}-{digest[:12]}"


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

    return Finding(
        id=derive_finding_id(rule_id, selector_str),
        rule_id=rule_id,
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


def build_conformance_map(findings: list[Finding]) -> dict[str, str]:
    """
    Collapse findings to one outcome per success criterion, worst-first.

    A plain `{f.sc.id: f.outcome for f in findings}` is last-write-wins, and
    the write order is not neutral: violations are mapped before incomplete
    items, and both `color-contrast` buckets carry SC 1.4.3. So an
    undecided `cantTell` would overwrite a proven `fail` and the report
    would understate a real conformance failure.

    Waived findings are excluded. A waiver is an accepted, justified
    failure — it must not keep the criterion marked as failing, or waiving
    a finding would have no effect on the conformance picture at all.
    """
    conformance: dict[str, str] = {}
    for finding in findings:
        if finding.waived:
            continue
        current = conformance.get(finding.sc.id)
        if current is None or _OUTCOME_RANK[finding.outcome] > _OUTCOME_RANK[current]:
            conformance[finding.sc.id] = finding.outcome
    return conformance


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

    scan_start_time = time.perf_counter()

    client = RPCClient(command=node_worker_command, default_timeout=timeout)

    try:
        await client.start()

        # Step 1: Request Page Render from Node worker
        logger.info(f"Requesting render for: {url}")
        # Support both .call() and .send_request() depending on RPCClient method name
        rpc_call = getattr(client, "call", client.send_request)
        render_start = time.perf_counter()
        render_result = await rpc_call("render", {"url": url})
        render_seconds = time.perf_counter() - render_start

        # Extract artifactId and nested content_hash under page_state
        artifact_id = render_result.get("artifactId")
        if not artifact_id:
            raise ValueError("Node worker render response missing required 'artifactId' field.")

        # `page_state_hash` is what ties a finding to the exact page state it
        # was observed in — it is the join key for baseline diffing (Week 7)
        # and for re-running a single finding. A placeholder here would make
        # every finding on every page appear to share one state, so a missing
        # content hash is a broken contract with the worker, not a default.
        page_state = render_result.get("page_state")
        if not isinstance(page_state, dict) or not page_state.get("content_hash"):
            raise ValueError(
                "Node worker render response missing required "
                "'page_state.content_hash'; findings cannot be attributed "
                "to a page state."
            )
        content_hash = page_state["content_hash"]

        # Step 2: Request Accessibility Analysis using 'runAxe' and artifactId
        logger.info(f"Requesting runAxe analysis for artifact: {artifact_id}")
        analysis_start = time.perf_counter()
        analysis_result = await rpc_call("runAxe", {"artifactId": artifact_id})
        analysis_seconds = time.perf_counter() - analysis_start

        # Extract both buckets
        raw_violations = analysis_result.get("violations", [])
        raw_incomplete = analysis_result.get("incomplete", [])

        # Step 3: Map Raw Violations to Validated Findings
        findings: list[Finding] = []
        non_wcag: list[str] = []
        
        # Process definitive violations
        for raw_v in raw_violations:
            if not isinstance(raw_v, dict):
                continue
            if extract_sc_id(raw_v.get("tags", [])) is None:
                non_wcag.append(raw_v.get("id", "unknown-rule"))
                continue
            findings.append(
                map_raw_violation_to_finding(raw_v, page_state_hash=content_hash)
            )

        # Process incomplete contrast findings
        for raw_inc in raw_incomplete:
            if not isinstance(raw_inc, dict):
                continue
            # We specifically want to route 'color-contrast' incomplete items to our agent
            if raw_inc.get("id") != "color-contrast":
                continue
            # Same guard the violations loop applies. Without it, an axe
            # release that retags `color-contrast` makes the mapper raise and
            # takes the entire scan down, rather than dropping one node.
            if extract_sc_id(raw_inc.get("tags", [])) is None:
                non_wcag.append(raw_inc.get("id", "unknown-rule"))
                continue
            mapped_finding = map_raw_violation_to_finding(raw_inc, page_state_hash=content_hash)
            # Override the default AUTHORITATIVE provenance to NEEDS_REVIEW
            findings.append(flag_needs_review(mapped_finding))

        if non_wcag:
            logger.info(
                "Excluded %d non-WCAG (best-practice) finding(s) from the "
                "conformance report: %s",
                len(non_wcag),
                ", ".join(sorted(set(non_wcag))),
            )
            
        # Step 3.5: Deduplicate and apply waivers
        findings = process_findings(findings)

        # Step 4: Build Conformance Map
        conformance_map = build_conformance_map(findings)

        total_seconds = time.perf_counter() - scan_start_time
        latency = Latency(
            render_seconds=render_seconds,
            analysis_seconds=analysis_seconds,
            total_seconds=total_seconds,
        )
        logger.info(
            "End-to-end page latency: %.2fs (render %.2fs, analysis %.2fs)",
            total_seconds,
            render_seconds,
            analysis_seconds,
        )

        # Step 5: Return Final Audit Report
        return AuditReport(
            target=url,
            standard="WCAG2.2-AA",
            findings=findings,
            conformance=conformance_map,
            verity_version="0.1.0",
            ruleset_version="1.0.0",
            latency=latency,
        )

    finally:
        # Guaranteed process cleanup
        await client.stop()