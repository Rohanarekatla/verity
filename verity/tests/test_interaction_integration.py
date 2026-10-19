"""
Week 9 end to end — APG contract findings reach a real `scan_url()` report.

End-to-end testing found the contract runner built, gated and unwired: a
`verity scan` of a click-only <div role="button"> disclosure exited 0. These
pin the wiring, the doctrine (a correct widget gates nothing), and that the
runner runs last, after the stages that read the rendered state.
"""

from pathlib import Path

import pytest

from verity.models.schemas import AuditReport, Provenance

REPO = Path(__file__).resolve().parents[2]
WORKER_JS = REPO / "node-worker" / "dist" / "rpc" / "server.js"
APG = REPO / "data" / "fixtures" / "apg"

pytestmark = pytest.mark.skipif(
    not WORKER_JS.exists(),
    reason="node worker not built (cd node-worker && npm run build)",
)


async def scan(name: str) -> AuditReport:
    from verity.orchestrator.main import scan_url

    return await scan_url(
        (APG / name).as_uri(), node_worker_command=["node", str(WORKER_JS)], timeout=90.0
    )


def apg(report: AuditReport) -> list:
    return [f for f in report.findings if f.agent == "interaction"]


def gating(report: AuditReport) -> list:
    from verity.report.policy import DEFAULT_POLICY

    return DEFAULT_POLICY.gating_findings(report.findings)


@pytest.mark.asyncio
async def test_click_only_disclosure_fails_the_scan():
    report = await scan("disclosure-fail.html")
    failed = {f.rule_id for f in apg(report) if f.outcome == "fail"}
    assert "apg-disclosure-enter-toggles" in failed
    assert any(f.agent == "interaction" for f in gating(report)), "the defect must gate the build"


@pytest.mark.asyncio
async def test_correct_widgets_gate_nothing():
    for page in ("disclosure-pass.html", "menu-button-pass.html", "tablist-pass.html"):
        report = await scan(page)
        assert apg(report), f"{page}: no interaction findings at all — runner unwired?"
        bad = [f.rule_id for f in apg(report)
               if f.outcome == "fail" and f.provenance is Provenance.AUTHORITATIVE]
        assert bad == [], f"{page}: false alarm(s) {bad}"


@pytest.mark.asyncio
async def test_contracts_run_after_the_keyboard_traversal():
    """
    The runner opens menus and toggles disclosures. Run before the traversal,
    the traversal would see a different page; the traversal's findings on the
    pass fixture must be exactly as clean as without the runner.
    """
    report = await scan("menu-button-pass.html")
    keyboard = [f for f in report.findings if f.agent == "keyboard"]
    assert keyboard and not [f for f in keyboard if f.outcome == "fail"]
