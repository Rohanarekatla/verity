"""Week 16, Track B — the ACR / VPAT 2.5 generator (B16.1, B16.2)."""

import pytest

from verity.acr import AI_LABEL, ManualResult, build_acr, load_manual, render_html, render_markdown
from verity.models.schemas import (
    AuditReport, Confidence, Evidence, Finding, Level, Modality, Provenance, Severity, SuccessCriterion,
)


def F(sc, prov=Provenance.AUTHORITATIVE, outcome="fail", fid="f", sel="#x", waived=False):
    conf = {Provenance.AUTHORITATIVE: Confidence(score=1.0, method="deterministic"),
            Provenance.AI_ASSISTED: Confidence(score=0.6, method="vision", model="qwen"),
            Provenance.NEEDS_REVIEW: Confidence(score=0.0, method="review")}[prov]
    f = Finding(id=fid, rule_id="r", sc=SuccessCriterion(id=sc, name="n", level=Level.A, modality=Modality.PARTIAL),
                provenance=prov, severity=Severity.SERIOUS, confidence=conf, agent="a", outcome=outcome,
                message="m", evidence=Evidence(dom_selector=sel), page_state_hash="h")
    f.waived = waived
    return f


def R(target, *findings):
    return AuditReport(target=target, standard="WCAG2.2-AA", findings=list(findings), conformance={},
                       verity_version="0.1.0", ruleset_version="1.0.0")


def rows(acr):
    return {r.sc: r for r in acr.rows}


def test_every_criterion_gets_a_row():
    acr = build_acr([R("p1")], product="Acme")
    assert len(acr.rows) == 56            # 55 A/AA in force + 4.1.1 for completeness
    assert len(build_acr([R("p1")], product="Acme", levels=("A", "AA", "AAA")).rows) == 87


def test_automation_never_claims_supports():
    acr = build_acr([R("p1"), R("p2")], product="Acme")
    assert not any(r.value == "Supports" for r in acr.rows)
    assert rows(acr)["2.1.2"].value == "Not Evaluated" and "not proof of conformance" in rows(acr)["2.1.2"].remarks
    assert rows(acr)["1.2.5"].value == "Not Evaluated" and "Not testable automatically" in rows(acr)["1.2.5"].remarks
    assert not acr.complete and "DRAFT" in render_markdown(acr)


def test_failures_map_by_share_of_pages():
    one_of_three = build_acr([R("p1", F("1.4.3")), R("p2"), R("p3")], product="Acme")
    assert rows(one_of_three)["1.4.3"].value == "Partially Supports"
    two_of_three = build_acr([R("p1", F("1.4.3")), R("p2", F("1.4.3")), R("p3")], product="Acme")
    r = rows(two_of_three)["1.4.3"]
    assert r.value == "Does Not Support"
    assert "2 of 3 pages" in r.remarks and "To fix:" in r.remarks and r.evidence


def test_ai_assisted_only_is_labelled_and_never_decided():
    acr = build_acr([R("p1", F("1.1.1", prov=Provenance.AI_ASSISTED, outcome="fail"))], product="Acme")
    r = rows(acr)["1.1.1"]
    assert r.value == "Not Evaluated" and r.ai_assisted and AI_LABEL in r.remarks


def test_waived_findings_do_not_count():
    acr = build_acr([R("p1", F("1.4.3", waived=True))], product="Acme")
    assert rows(acr)["1.4.3"].value == "Not Evaluated"


def test_human_results_override_and_can_complete_the_report(tmp_path):
    manual_path = tmp_path / "manual.yaml"
    manual_path.write_text("1.2.5:\n  value: Not Applicable\n  remarks: No video.\n  evaluator: N. Chunduri\n",
                           encoding="utf-8")
    manual = load_manual(manual_path)
    acr = build_acr([R("p1")], product="Acme", manual=manual)
    assert rows(acr)["1.2.5"].value == "Not Applicable" and "N. Chunduri" in rows(acr)["1.2.5"].remarks
    everything = {r.sc: ManualResult("Supports", "Checked by hand.") for r in acr.rows}
    done = build_acr([R("p1")], product="Acme", manual=everything)
    assert done.complete and "DRAFT" not in render_markdown(done)


def test_bad_manual_value_is_rejected(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("1.1.1: Fully Compliant\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a VPAT value"):
        load_manual(p)


def test_html_is_an_accessible_table():
    html = render_html(build_acr([R("p1", F("4.1.2"))], product="Acme <Store>"))
    assert '<html lang="en">' in html and "<caption>" in html and 'scope="row"' in html
    assert "Acme &lt;Store&gt;" in html and 'role="alert"' in html
