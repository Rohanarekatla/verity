"""
B9.4 (Track B, Week 9) — ARIA-misuse injectors, and the half of Week 9's
gate they exist for: **all injected misuse fails**.

The structural tests run everywhere (BeautifulSoup only). The gate test
injects each misuse into a correct APG pass fixture, renders it through the
real worker, runs the contracts, and requires the named `violation` to FAIL —
skipped when the worker is not built, like test_contract_gate.py. The other
half of the gate, zero false alarms on the clean fixtures, is A9.4's
`test_contract_fixture_gate`.
"""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from eval.inject.aria_misuse import INJECTORS, MISSING_ID

REPO = Path(__file__).resolve().parents[2]
APG = REPO / "data" / "fixtures" / "apg"
WORKER_JS = REPO / "node-worker" / "dist" / "rpc" / "server.js"

needs_worker = pytest.mark.skipif(
    not WORKER_JS.exists(),
    reason="node worker not built (cd node-worker && npm run build)",
)

# (pass fixture, injector, selector, kwargs, contract, assertion that must fail)
CASES = [
    ("disclosure-pass.html", "click_only_widget", "#faq-1", {}, "disclosure", "enter-toggles"),
    ("dialog-pass.html", "click_only_widget", "#open-address", {}, "dialog", "enter-opens-dialog"),
    ("menu-button-pass.html", "click_only_widget", "#actions", {}, "menu-button", "enter-opens-menu"),
    ("menu-button-pass.html", "strip_accessible_name", "#actions", {}, "menu-button", "trigger-has-accessible-name"),
    ("tablist-pass.html", "strip_accessible_name", "#tab-2", {}, "tablist", "tab-has-accessible-name"),
    ("disclosure-pass.html", "invalid_aria_state", "#faq-1", {}, "disclosure", "aria-expanded-is-boolean"),
    ("combobox-pass.html", "invalid_aria_state", "#state", {}, "combobox", "aria-expanded-is-boolean"),
    ("menu-button-pass.html", "dangling_idref", "#actions", {}, "menu-button", "controls-a-menu"),
    ("dialog-pass.html", "dangling_idref", "#open-address", {}, "dialog", "controls-a-dialog"),
    ("combobox-pass.html", "dangling_idref", "#state", {}, "combobox", "controls-a-popup"),
    ("tablist-pass.html", "wrong_role", '[role="tabpanel"]', {}, "tablist", "controlled-element-is-a-tabpanel"),
    ("tablist-pass.html", "remove_from_tab_order", '[role="tab"]', {}, "tablist", "roving-tabindex"),
]


def _norm(html: str) -> str:
    return BeautifulSoup(html, "html.parser").decode()


# --- structural: the defect is introduced, and only that defect ------------------

@pytest.mark.parametrize("fixture, injector, selector, kwargs", [c[:4] for c in CASES])
def test_every_injector_changes_the_page_and_reverts_exactly(fixture, injector, selector, kwargs):
    clean = (APG / fixture).read_text(encoding="utf-8")
    inj = INJECTORS[injector]
    injected = inj.inject(clean, selector, **kwargs)
    assert _norm(injected) != _norm(clean), f"{injector} changed nothing on {fixture}"
    assert _norm(inj.revert(injected, selector)) == _norm(clean)


def test_click_only_widget_keeps_the_role_and_focusability_but_not_the_button():
    out = INJECTORS["click_only_widget"].inject('<button id="b" aria-expanded="false">More</button>', "#b")
    el = BeautifulSoup(out, "html.parser").select_one("#b")
    assert el.name == "div"
    assert el["role"] == "button" and el["tabindex"] == "0"
    assert el["aria-expanded"] == "false" and el.get_text() == "More", "everything static stays correct"


def test_click_only_widget_keeps_an_authored_role_and_tabindex():
    html = '<button id="t" role="tab" tabindex="-1">One</button>'
    inj = INJECTORS["click_only_widget"]
    el = BeautifulSoup(inj.inject(html, "#t"), "html.parser").select_one("#t")
    assert el["role"] == "tab" and el["tabindex"] == "-1"
    assert _norm(inj.revert(inj.inject(html, "#t"), "#t")) == _norm(html)


def test_strip_accessible_name_removes_every_naming_source_and_restores_markup():
    html = '<button id="b" aria-label="Close" title="Close dialog"><span class="x">×</span></button>'
    inj = INJECTORS["strip_accessible_name"]
    el = BeautifulSoup(inj.inject(html, "#b"), "html.parser").select_one("#b")
    assert el.get_text() == "" and not el.has_attr("aria-label") and not el.has_attr("title")
    assert _norm(inj.revert(inj.inject(html, "#b"), "#b")) == _norm(html)


def test_dangling_idref_points_at_an_id_that_cannot_exist():
    out = INJECTORS["dangling_idref"].inject('<button id="b" aria-controls="m">Menu</button><ul id="m"></ul>', "#b")
    soup = BeautifulSoup(out, "html.parser")
    assert soup.select_one("#b")["aria-controls"] == MISSING_ID
    assert soup.select_one(f"#{MISSING_ID}") is None


def test_wrong_role_reverts_even_though_the_selector_no_longer_matches():
    html = '<div role="tabpanel" id="p1">A</div><div role="tabpanel" id="p2">B</div>'
    inj = INJECTORS["wrong_role"]
    injected = inj.inject(html, '[role="tabpanel"]')
    assert not BeautifulSoup(injected, "html.parser").select('[role="tabpanel"]')
    assert _norm(inj.revert(injected, '[role="tabpanel"]')) == _norm(html)


def test_injecting_twice_keeps_the_true_original():
    html = '<button id="b" aria-expanded="false">More</button>'
    inj = INJECTORS["invalid_aria_state"]
    twice = inj.inject(inj.inject(html, "#b"), "#b")
    assert _norm(inj.revert(twice, "#b")) == _norm(html)


def test_injectors_touch_only_the_selected_elements():
    html = '<button id="a" aria-expanded="false">A</button><button id="b" aria-expanded="false">B</button>'
    for name in ("invalid_aria_state", "dangling_idref", "remove_from_tab_order", "click_only_widget",
                 "strip_accessible_name"):
        out = BeautifulSoup(INJECTORS[name].inject(html, "#a"), "html.parser")
        assert str(out.select_one("#b")) == str(BeautifulSoup(html, "html.parser").select_one("#b")), name


# --- the gate: every injected misuse fails its violation ---------------------------

@needs_worker
@pytest.mark.asyncio
async def test_every_injected_aria_misuse_fails_a_violation(tmp_path):
    from verity.agents.interaction import run_contracts_on_artifact
    from verity.orchestrator.rpc_client import RPCClient
    from verity.rulepacks import Severity

    client = RPCClient(command=["node", str(WORKER_JS)], default_timeout=60.0)
    await client.start()
    missed: list[str] = []
    try:
        for i, (fixture, injector, selector, kwargs, contract, assertion) in enumerate(CASES):
            page = tmp_path / f"{i:02d}-{injector}-{fixture}"
            page.write_text(INJECTORS[injector].inject((APG / fixture).read_text(encoding="utf-8"),
                                                       selector, **kwargs), encoding="utf-8")
            render = await client.send_request("render", {"url": page.as_uri()})
            try:
                run = await run_contracts_on_artifact(client.send_request, render["artifactId"])
            finally:
                await client.send_request("releaseArtifact", {"artifactId": render["artifactId"]})
            hits = [r for r in run.results if r.contract == contract and r.assertion_id == assertion]
            if not any(r.outcome == "fail" and r.severity is Severity.VIOLATION for r in hits):
                seen = [(r.outcome, r.severity.value, r.detail) for r in hits] or "no result (widget not matched?)"
                missed.append(f"{injector} on {fixture}: {contract}/{assertion} did not fail — {seen}")
    finally:
        await client.stop()
    assert missed == [], "\n".join(missed)
