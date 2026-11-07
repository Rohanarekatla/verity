"""
Week 14, Track B — agent-check confirmation (B14.1′), the agent-readiness score
(B14.2′), and the per-SC precision/recall harness, coverage metric and
baseline freeze (B14.3).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from eval.precision_recall import (
    EXHAUSTIVE,
    Label,
    compare_to_baseline,
    finding_targets,
    freeze,
    manifest_digest,
    score,
)
from verity.agent_check.check import Localization
from verity.agent_check.confirm import ElementFacts, confirm_from_facts, confirmation_metrics, decide
from verity.agents.virtual_sr import load_ax_tree
from verity.models.schemas import Provenance
from verity.readiness import TaskOutcome, render_markdown, score as readiness_score, static_points
from verity.standards import AXE_SC, WCAG22, active, coverage_summary, method

REPO = Path(__file__).resolve().parents[2]
LOC = Localization(step=3, sc_id="4.1.2", reason="r", selector='[data-vbid="7"]')


# --- B14.1′ confirmation ------------------------------------------------------------

@pytest.mark.parametrize("facts, expected", [
    (ElementFacts(exists=True, role="button", name=""), ("fail", "unnamed-control")),
    (ElementFacts(exists=True, role="textbox", name=None), ("fail", "unnamed-control")),
    (ElementFacts(exists=True, role="generic", click_listener=True, focusable=False), ("fail", "roleless-clickable")),
])
def test_textbook_failures_are_confirmed(facts, expected):
    assert decide(LOC, facts) == expected


@pytest.mark.parametrize("facts", [
    None,
    ElementFacts(exists=False),
    ElementFacts(exists=True, role="button", name="Submit"),           # it has a name now
    ElementFacts(exists=True, role="button", name="", ignored=True),   # hidden
    ElementFacts(exists=True, role="button", name="", disabled=True),
    ElementFacts(exists=True, role="generic", click_listener=False),   # cursor:pointer is not evidence
    ElementFacts(exists=True, role="generic", click_listener=True, focusable=True),
    ElementFacts(exists=True, role="button", name="", errors=["accessibility node: TimeoutError"]),
])
def test_anything_short_of_proof_is_needs_review(facts):
    outcome, _ = decide(LOC, facts)
    assert outcome == "cantTell"
    prov, conf, out = confirm_from_facts(LOC, facts)
    assert prov is Provenance.NEEDS_REVIEW and out == "cantTell" and conf.score == 0.0


def test_a_confirmation_is_coherent_authoritative_provenance():
    prov, conf, out = confirm_from_facts(LOC, ElementFacts(exists=True, role="link", name=""))
    assert prov is Provenance.AUTHORITATIVE and out == "fail" and conf.score == 1.0 and conf.model is None


def test_confirmation_gate_requires_zero_wrong_confirmations():
    good = [{"defect": "strip_name", "failed": True, "localized_marker": "strip_name", "confirmed": True}] * 9 + \
           [{"defect": "strip_name", "failed": True, "localized_marker": None, "confirmed": False}]
    m = confirmation_metrics(good)
    assert m["localization_rate"] == 0.9 and m["wrong_confirmations"] == 0 and m["gate_passed"]
    bad = good + [{"defect": None, "failed": True, "localized_marker": None, "confirmed": True}]
    assert confirmation_metrics(bad)["wrong_confirmations"] == 1 and not confirmation_metrics(bad)["gate_passed"]


# --- B14.2′ readiness -----------------------------------------------------------------

def _n(i, role, name=None, kids=(), parent=None, ignored=False, **props):
    raw = {"nodeId": i, "ignored": ignored, "role": {"value": role}, "childIds": list(kids),
           "properties": [{"name": k, "value": {"value": v}} for k, v in props.items()]}
    if name is not None:
        raw["name"] = {"value": name}
    if parent:
        raw["parentId"] = parent
    return raw


def tree(button_name="Buy", extra=()):
    return load_ax_tree({"nodes": [
        _n("1", "RootWebArea", "Shop", ["2"]),
        _n("2", "main", None, ["3", "4", "5", *[e["nodeId"] for e in extra]], "1"),
        _n("3", "heading", "Products", [], "2", level=1),
        _n("4", "button", button_name, [], "2", focusable=True),
        _n("5", "link", "Home", [], "2", focusable=True),
        *extra,
    ]})


def test_a_well_built_page_earns_every_measured_point_with_evidence():
    pts = {p.id: p for p in static_points(tree(), findings=[], second_tree=tree())}
    assert pts["named_controls"].earned == 30 and pts["structure"].earned == 15
    assert pts["well_formed"].earned == 15 and pts["stability"].earned == 10 and pts["wcag_blockers"].earned == 10
    assert pts["webmcp"].status == "not_measured"
    assert all(p.evidence for p in pts.values())
    r = readiness_score(list(pts.values()))
    assert r.static_score == 100 and r.static_coverage == pytest.approx(80 / 100)
    assert any("webmcp" in n for n in r.notes)


def test_unmeasured_points_never_count_as_earned():
    r = readiness_score(static_points(tree()))
    assert {p.id for p in r.points if p.status == "not_measured"} == {"stability", "wcag_blockers", "webmcp"}
    assert r.static_coverage == pytest.approx(60 / 100)


def test_an_unnamed_control_costs_points_and_is_named_in_the_evidence():
    pts = {p.id: p for p in static_points(tree(button_name=""))}
    assert pts["named_controls"].earned == 15
    assert any("unnamed button" in e for e in pts["named_controls"].evidence)


def test_a_focusable_node_hidden_from_the_tree_is_not_well_formed():
    hidden = _n("6", "generic", None, [], "2", ignored=True, focusable=True)
    pts = {p.id: p for p in static_points(tree(extra=(hidden,)))}
    assert pts["well_formed"].earned < 15


def test_dynamic_failures_only_blame_the_site_when_confirmed():
    r = readiness_score(static_points(tree()), [TaskOutcome("buy", True), TaskOutcome("search", False)])
    assert r.dynamic_score == 50 and r.overall == pytest.approx((100 + 50) / 2)
    assert any("not confirmed" in n for n in r.notes)
    assert "needs review" in render_markdown(r)


# --- B14.3 standards table, coverage, P/R harness, baseline freeze ---------------------

def test_wcag22_table_is_complete():
    assert len(WCAG22) == 87 and len(active()) == 86
    levels = [c.level for c in active()]
    assert (levels.count("A"), levels.count("AA"), levels.count("AAA")) == (31, 24, 31)
    assert len({c.id for c in WCAG22}) == 87


def test_coverage_is_published_with_its_gaps():
    cov = coverage_summary(("A", "AA"))
    assert cov["criteria"] == 55
    assert cov["attempted"] + len(cov["not_attempted"]) == 55
    assert "1.2.5" in cov["not_attempted"]          # audio description: never pretended
    assert method("1.4.3") == "deterministic" and method("3.1.5") == "manual"


@pytest.mark.skipif(shutil.which("node") is None or not (REPO / "node-worker" / "node_modules" / "axe-core").exists(),
                    reason="axe-core not installed")
def test_axe_sc_matches_axe_cores_own_rule_tags():
    js = ("const axe=require('axe-core');const s=new Set();for(const r of axe.getRules()){"
          "if(r.tags.includes('experimental')||r.tags.includes('deprecated'))continue;"
          "for(const t of r.tags)if(/^wcag\\d{3,4}$/.test(t)){const d=t.slice(4);s.add(d[0]+'.'+d[1]+'.'+d.slice(2));}}"
          "console.log(JSON.stringify([...s]));")
    out = subprocess.run(["node", "-e", js], cwd=REPO / "node-worker", capture_output=True, text=True, check=True)
    from verity.standards import BY_ID

    derived = {sc for sc in json.loads(out.stdout) if sc in BY_ID and BY_ID[sc].level in ("A", "AA")
               and not BY_ID[sc].obsolete}
    assert derived == set(AXE_SC)


def F(sc, sel, prov="authoritative", outcome="fail", fid=None, **cv):
    return {"id": fid or f"{sc}-{sel}", "sc": {"id": sc}, "provenance": prov, "outcome": outcome,
            "evidence": {"dom_selector": sel, "computed_values": cv}}


def test_finding_targets_read_selectors_and_keyboard_lists():
    f = F("2.1.1", "body > div", unreachable=["#stranded"], positive_tabindex=[{"selector": "#jumped"}])
    assert finding_targets(f) == {"stranded", "jumped"}


def test_per_sc_precision_and_recall():
    labels = [Label("a.html", "2.1.1", "x", "fail"), Label("b.html", "2.1.1", "y", "fail"),
              Label("c.html", "2.1.1", "z", "pass")]
    findings = {"a.html": [F("2.1.1", "#x")], "b.html": [F("2.1.1", "#y", prov="needs review", outcome="cantTell")],
                "c.html": [F("2.1.1", "#z")], "clean.html": [F("4.1.2", "#w")]}
    s = score(labels, findings, {"clean.html": ("4.1.2",)})
    assert (s["2.1.1"]["tp"], s["2.1.1"]["fn"], s["2.1.1"]["fp"], s["2.1.1"]["review"]) == (1, 1, 1, 1)
    assert s["2.1.1"]["precision"] == 0.5 and s["2.1.1"]["recall"] == 0.5
    assert s["4.1.2"]["fp"] == 1 and s["4.1.2"]["precision"] == 0.0


def test_a_deliberate_regression_fails_the_check(tmp_path):
    good = {"2.1.1": {"tp": 4, "fp": 0, "fn": 0, "tn": 1, "review": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}}
    path = freeze(good, "9.9.9", digest="abc", path=tmp_path / "9.9.9.json")
    frozen = json.loads(path.read_text())
    assert compare_to_baseline(good, frozen, digest="abc") == []
    worse = {"2.1.1": {**good["2.1.1"], "tp": 3, "fn": 1, "recall": 0.75}}
    assert any("recall" in p for p in compare_to_baseline(worse, frozen, digest="abc"))
    noisier = {"2.1.1": {**good["2.1.1"], "fp": 1, "precision": 0.8}}
    assert any("false positives" in p for p in compare_to_baseline(noisier, frozen, digest="abc"))
    assert "corpus changed" in compare_to_baseline(good, frozen, digest="other")[0]


def test_the_corpus_manifest_exists_and_is_hashable():
    assert len(manifest_digest()) == 64
    assert all((REPO / "data" / "fixtures" / p).exists() for p in EXHAUSTIVE)
