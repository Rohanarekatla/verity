"""
Week 15, Track B — the verifier-gated fix loop (B15.1′), the fix evaluation's
metrics (B15.2′), and the EARL report (B15.3). The loop is exercised with a
fake scanner that reads the sandbox file, so acceptance is decided by real
file contents without a browser.
"""

import json
from pathlib import Path

import pytest

from eval.fix_eval import CaseResult, FixCase, fix_metrics
from verity.remediation.fix_loop import (
    Patch,
    RulePatcher,
    apply_patch,
    fix_finding,
    parse_patch,
    verify,
)

REPO = Path(__file__).resolve().parents[2]

PAGE = """<!doctype html>
<html lang="en"><head><title>t</title></head>
<body>
  <button id="go" tabindex="7">Go</button>
  <button id="other">Other</button>
</body></html>
"""


def finding(sc="2.4.3", rule="positive-tabindex", sel="#go", fid="f1"):
    return {"id": fid, "sc": {"id": sc}, "rule_id": rule, "outcome": "fail", "provenance": "authoritative",
            "message": "positive tabindex", "evidence": {"dom_selector": sel}}


def fake_scan(path: str) -> list[dict]:
    """A 'scanner' that reports a positive tabindex on #go, and a new defect if the page lost #other."""
    text = Path(path).read_text(encoding="utf-8")
    out = []
    if 'id="go" tabindex="7"' in text:
        out.append(finding())
    if 'id="other"' not in text:
        out.append(finding(sc="4.1.2", rule="button-name", sel="#broken", fid="f2"))
    return out


class ScriptedPatcher:
    def __init__(self, patches):
        self.patches, self.feedback, self.last_cost = list(patches), [], 0.01

    def propose(self, finding, loc, source, feedback):
        self.feedback.append(list(feedback))
        return self.patches.pop(0) if self.patches else None


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    return root


def test_a_correct_patch_is_accepted_and_the_user_tree_is_untouched_until_applied(project):
    patcher = ScriptedPatcher([Patch("", '<button id="go" tabindex="7">', '<button id="go">')])
    r = fix_finding(finding(), project_root=project, page="index.html", scan_fn=fake_scan, patcher=patcher)
    assert r.accepted and r.lines_changed == 2 and "-  <button id=\"go\" tabindex=\"7\">" in r.diff
    assert 'tabindex="7"' in (project / "index.html").read_text(), "nothing written before apply_to"
    r.apply_to(project)
    assert 'tabindex="7"' not in (project / "index.html").read_text()
    assert r.cost_usd == pytest.approx(0.01)


def test_a_patch_that_introduces_a_regression_is_refused_and_retried(project):
    breaking = Patch("", '  <button id="go" tabindex="7">Go</button>\n  <button id="other">Other</button>',
                     '  <button id="go">Go</button>')
    good = Patch("", ' tabindex="7"', "")
    patcher = ScriptedPatcher([breaking, good])
    r = fix_finding(finding(), project_root=project, page="index.html", scan_fn=fake_scan, patcher=patcher)
    assert r.accepted and len(r.attempts) == 2
    assert not r.attempts[0].accepted and "new failure" in r.attempts[0].reasons[0]
    assert "new failure" in patcher.feedback[1][0], "the refusal reason is fed back to the patcher"


def test_a_patch_that_leaves_broken_markup_is_refused_even_if_the_defect_is_gone(project):
    # The 31 Oct demo patch: the opening <span> was dropped, its closing tag left behind.
    page = '<button id="go"><span aria-hidden="true">Go</span></button>'
    (project / "index.html").write_text(f"<body>{page}</body>", encoding="utf-8")
    sloppy = Patch("", '<button id="go"><span aria-hidden="true">Go</span></button>',
                   '<button id="go" aria-label="Go">Go</span></button>')
    sound = Patch("", '<span aria-hidden="true">Go</span>', "Go")
    scan = lambda path: [finding(sel="#go")] if "aria-hidden" in Path(path).read_text() else []   # defect = hidden name
    patcher = ScriptedPatcher([sloppy, sound])
    r = fix_finding(finding(sel="#go"), project_root=project, page="index.html", scan_fn=scan, patcher=patcher)
    assert not r.attempts[0].accepted and "stray </span>" in r.attempts[0].reasons[0]
    assert "stray </span>" in patcher.feedback[1][0], "the reason is fed back so the model can correct it"
    assert r.accepted and len(r.attempts) == 2


def test_markup_check_only_blames_what_the_patch_added():
    from verity.remediation.fix_loop import markup_regressions
    sloppy = "<div><p>one<p>two</div></i>"            # optional </p> and a stray </i> already there
    assert markup_regressions(sloppy, sloppy.replace("one", "uno")) == []
    assert markup_regressions("<b>x</b>", "<b>x</span></b>") == ["the patch broke the markup: stray </span>"]
    assert markup_regressions("<b>x</b>", "<b><i>x</b>") == ["the patch broke the markup: unclosed <i>"]
    assert markup_regressions('<img src="a"><br>', '<img src="a" alt="a"><br>') == []   # void elements are fine


def test_after_three_refusals_it_hands_off_with_every_reason(project):
    patcher = ScriptedPatcher([Patch("", "not in the file", "x")] * 3)
    r = fix_finding(finding(), project_root=project, page="index.html", scan_fn=fake_scan, patcher=patcher)
    assert not r.accepted and len(r.attempts) == 3 and len(r.handoff) == 3
    assert all("does not occur" in h for h in r.handoff)
    with pytest.raises(RuntimeError):
        r.apply_to(project)


def test_unlocatable_element_is_handed_off(project):
    r = fix_finding(finding(sel="#nope"), project_root=project, page="index.html", scan_fn=fake_scan,
                    patcher=ScriptedPatcher([]))
    assert not r.accepted and "could not locate" in r.handoff[0]


def test_patches_must_be_unique_exact_replacements():
    assert apply_patch("a b a", Patch("", "a", "c"))[1].endswith("must be unique")
    assert apply_patch("abc", Patch("", "abc", "abc"))[1] == "the patch changes nothing"
    assert apply_patch("abc", Patch("", "b", "B"))[0] == "aBc"


def test_verify_requires_resolved_and_no_new_failure():
    t = finding()
    assert verify([t], [], t)[0]
    assert not verify([t], [t], t)[0]
    assert not verify([t], [finding(sc="1.1.1", rule="image-alt", sel="#x", fid="z")], t)[0]


def test_parse_patch_from_model_text():
    p = parse_patch('Sure: ```json\n{"old": "tabindex=\\"7\\"", "new": "", "rationale": "remove"}\n```')
    assert p and p.old == 'tabindex="7"' and p.new == ""
    assert parse_patch("I cannot help") is None


def test_rule_patcher_removes_a_positive_tabindex(project):
    from verity.remediation.source_map import locate_selector

    loc = locate_selector("#go", project)
    p = RulePatcher().propose(finding(), loc, PAGE, [])
    assert p and "tabindex" not in p.new and "tabindex" in p.old


def test_rule_patcher_never_invents_a_text_alternative(project):
    from verity.remediation.source_map import locate_selector

    loc = locate_selector("#go", project)
    assert RulePatcher().propose(finding(sc="1.1.1", rule="image-alt"), loc, PAGE, []) is None


# --- B15.2′ metrics -------------------------------------------------------------------

def C(family):
    return FixCase(family, family, "p.html", "strip_alt", "#x", ("1.1.1",), "x")


def test_fix_metrics_and_gate():
    rs = [CaseResult(C("alt"), True, accepted=True, fixed=True, lines_changed=2, cost_usd=0.01),
          CaseResult(C("name"), True, accepted=True, fixed=True, lines_changed=1, cost_usd=0.01),
          CaseResult(C("label"), True, accepted=False),
          CaseResult(C("contrast"), False)]
    m = fix_metrics(rs)
    assert m["found"] == 3 and m["fixed"] == 2 and abs(m["gate_fix_rate"] - 2 / 3) < 1e-9
    assert m["accepted_regressions"] == 0 and m["gate_passed"]
    rs[0].accepted_regression = True
    assert not fix_metrics(rs)["gate_passed"]


# --- B15.3 EARL -------------------------------------------------------------------------

def report_with(findings, conformance):
    from verity.models.schemas import AuditReport

    return AuditReport(target="https://example.com/checkout", standard="WCAG2.2-AA", findings=findings,
                       conformance=conformance, verity_version="0.1.0", ruleset_version="1.0.0")


def contrast_finding():
    from verity.models.schemas import (Confidence, Evidence, Finding, Level, Modality, Provenance, Severity,
                                       SuccessCriterion)

    return Finding(id="color-contrast-1", rule_id="color-contrast",
                   sc=SuccessCriterion(id="1.4.3", name="Contrast (Minimum)", level=Level.AA,
                                       modality=Modality.DETERMINISTIC),
                   provenance=Provenance.AUTHORITATIVE, severity=Severity.SERIOUS,
                   confidence=Confidence(score=1.0, method="wcag-contrast-arithmetic"), agent="contrast",
                   outcome="fail", message="low contrast", evidence=Evidence(dom_selector="#hero h1"),
                   page_state_hash="h")


def test_earl_matches_the_hand_written_assertion():
    from verity.report.earl import build_earl

    example = json.loads((REPO / "docs" / "earl-example.jsonld").read_text(encoding="utf-8"))
    graph = build_earl(report_with([contrast_finding()], {"1.4.3": "fail"}), date="2026-12-01T10:00:00Z")["@graph"]
    a = next(x for x in graph if x.get("dct:identifier") == "color-contrast-1")
    assert a["test"]["@id"] == example["test"]["@id"] == "WCAG22:contrast-minimum"
    assert a["result"]["outcome"] == example["result"]["outcome"] == "earl:failed"
    assert a["result"]["pointer"]["ptr:expression"] == example["result"]["pointer"]["ptr:expression"]
    assert a["mode"] == example["mode"]


def test_earl_marks_every_unjudged_aa_criterion_untested():
    from verity.report.earl import build_earl, wcag_anchor
    from verity.standards import active

    graph = build_earl(report_with([], {}))["@graph"]
    untested = [x for x in graph if x.get("result", {}).get("outcome") == "earl:untested"]
    assert len(untested) == len([c for c in active() if c.level in ("A", "AA")]) == 55
    assert wcag_anchor("4.1.2") == "name-role-value"
    assert wcag_anchor("3.3.4") == "error-prevention-legal-financial-data"
