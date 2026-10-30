"""
A15.1′ — the real capabilities behind the MCP tools.

The pure pieces — `explain_finding` and the confirm-hint mapping — are here and
tested directly; they are what a coding agent leans on most (read a finding,
learn which tool confirms its fix). The browser-backed pieces run one
`scan_url` and read the answer out of the report the engine already computes:
the full engine runs every agent on a scan, so `sample_contrast`, `traverse`
and `run_contract` are filtered reads of one scan, not four separate renders —
cheaper for the agent and the same numbers the scan reports.
"""

from __future__ import annotations

from typing import Optional

from verity.mcp.tools import ToolError

# Which MCP tool confirms a fix for each success criterion — the single most
# useful thing to tell a coding agent after it reads a finding.
_CONFIRM_BY_SC = {
    "1.1.1": "virtual_sr_read",
    "1.3.1": "run_contract",
    "1.4.3": "sample_contrast",
    "2.1.1": "traverse",
    "2.1.2": "traverse",
    "2.4.3": "traverse",
    "2.4.7": "traverse",
    "4.1.2": "run_contract",
}

_REMEDIATION = {
    "1.1.1": "Give the image a text alternative (alt), or mark it decorative (alt=\"\").",
    "1.4.3": "Raise the text/background contrast to at least 4.5:1 (3:1 for large text).",
    "2.1.1": "Make the control operable by keyboard: a real button/link, or key handlers + tabindex.",
    "2.1.2": "Ensure focus can leave the component by keyboard — remove the trap.",
    "2.4.7": "Give the focused element a visible focus indicator with sufficient contrast.",
    "4.1.2": "Give the control an accessible name and the correct role (native element or ARIA).",
}


def confirm_tool_for(sc_id: str) -> str:
    """The MCP tool that confirms a fix for this SC (defaults to a full scan)."""
    return _CONFIRM_BY_SC.get(sc_id, "scan")


def explain_finding(report: dict, finding_id: str) -> dict:
    """
    Pure: explain one finding from a scan report — its criterion, why it fails,
    how to fix it, and which tool confirms the fix. Raises ToolError if the id
    is not in the report, so the agent learns it passed a stale id.
    """
    findings = report.get("findings", []) if isinstance(report, dict) else []
    match = next((f for f in findings if f.get("id") == finding_id), None)
    if match is None:
        ids = ", ".join(f.get("id", "?") for f in findings[:8])
        raise ToolError(f"no finding {finding_id!r} in this report (have: {ids or 'none'})")
    sc = match.get("sc") or {}
    sc_id = sc.get("id", "")
    evidence = match.get("evidence") or {}
    return {
        "id": finding_id,
        "sc": sc_id,
        "sc_name": sc.get("name"),
        "level": sc.get("level"),
        "provenance": match.get("provenance"),
        "outcome": match.get("outcome"),
        "message": match.get("message"),
        "selector": evidence.get("dom_selector"),
        "remediation": match.get("remediation") or _REMEDIATION.get(sc_id,
                       "Resolve the reported condition; re-scan to confirm."),
        "confirm_with": confirm_tool_for(sc_id),
    }


def _family(sc_id: str) -> str:
    return {"1.1.1": "name", "1.4.3": "contrast", "4.1.2": "name", "1.3.1": "structure",
            "2.1.1": "keyboard", "2.1.2": "keyboard", "2.4.3": "keyboard", "2.4.7": "focus"}.get(sc_id, "other")


class _DefaultCapabilities:
    """Wraps the real engine. Not unit-tested (needs a browser + the node worker);
    exercised through the hand-done fix in the Week-15 artifact."""

    def __init__(self, *, timeout: float = 120.0):
        self.timeout = timeout
        self._cache: dict[str, dict] = {}

    # -- the one tool that renders -------------------------------------------

    def scan(self, url: str, *, config: Optional[str] = None) -> dict:
        import asyncio

        from verity.orchestrator.main import scan_url

        report = asyncio.run(scan_url(url=url, timeout=self.timeout))
        data = report.model_dump(mode="json")
        self._cache[url] = data
        return {
            "target": data["target"],
            "finding_count": len(data["findings"]),
            "findings": [{"id": f["id"], "sc": (f.get("sc") or {}).get("id"),
                          "provenance": f["provenance"], "outcome": f["outcome"],
                          "selector": (f.get("evidence") or {}).get("dom_selector"),
                          "message": f["message"]} for f in data["findings"]],
        }

    def _report(self, url: str) -> dict:
        if url not in self._cache:
            self.scan(url)
        return self._cache[url]

    # -- pure read over a scan -----------------------------------------------

    def explain_finding(self, report: dict, finding_id: str) -> dict:
        return explain_finding(report, finding_id)

    def _by_family(self, url: str, family: str, selector: Optional[str] = None) -> dict:
        report = self._report(url)
        hits = []
        for f in report["findings"]:
            sc_id = (f.get("sc") or {}).get("id", "")
            if _family(sc_id) != family:
                continue
            sel = (f.get("evidence") or {}).get("dom_selector")
            if selector and sel != selector:
                continue
            hits.append({"id": f["id"], "sc": sc_id, "outcome": f["outcome"],
                         "selector": sel, "message": f["message"],
                         "computed": (f.get("evidence") or {}).get("computed_values")})
        return {"url": url, "family": family, "findings": hits, "clean": not hits}

    def sample_contrast(self, url: str, selector: str) -> dict:
        return self._by_family(url, "contrast", selector)

    def traverse(self, url: str) -> dict:
        out = self._by_family(url, "keyboard")
        out["focus"] = self._by_family(url, "focus")["findings"]
        return out

    def run_contract(self, url: str, selector: Optional[str] = None) -> dict:
        report = self._report(url)
        hits = [f for f in report["findings"] if f.get("agent") == "interaction"
                and (not selector or (f.get("evidence") or {}).get("dom_selector") == selector)]
        return {"url": url, "findings": hits, "clean": not hits}

    def virtual_sr_read(self, url: str) -> dict:
        # Name/role failures are what the screen reader cannot announce.
        return self._by_family(url, "name")

    def baseline_diff(self, url: str, baseline_path: str, *, config: Optional[str] = None) -> dict:
        import asyncio

        from verity.orchestrator.main import scan_url
        from verity.report.baseline import format_diff
        from verity.report.policy import load_policy
        from verity.report.regression import gate_against_baseline, open_baseline

        baseline = open_baseline(baseline_path)
        if baseline is None:
            raise ToolError(f"no baseline at {baseline_path!r}")
        report = asyncio.run(scan_url(url=url, timeout=self.timeout))
        result = gate_against_baseline(baseline, report, load_policy(config))
        return {
            "url": url,
            "new": [f.id for f in result.diff.new],
            "fixed": list(result.diff.fixed),
            "gating": [f.id for f in result.gating],
            "summary": format_diff(result.diff),
            "regression_free": len(result.gating) == 0,
        }


def default_capabilities(*, timeout: float = 120.0) -> _DefaultCapabilities:
    return _DefaultCapabilities(timeout=timeout)
