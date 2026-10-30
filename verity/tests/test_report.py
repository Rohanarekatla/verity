"""
Tests for Week 8 Track B — SARIF (B8.1, B8.2), JUnit (B8.3) and the gating
policy (B8.4).

Week 8 is "the first useful thing": the surface a stranger judges the project
by. So these tests care about two things above all — that `level` tracks
*trust* rather than severity, and that nothing non-authoritative can turn a
build red.

Also writes `eval/fixtures/minimal.sarif.json`, so there is always a current
file to upload to a real repo when verifying annotations by hand. See
`docs/sarif-reference.md` §6.
"""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from verity.models.schemas import (
    AuditReport,
    Confidence,
    Evidence,
    Finding,
    Latency,
    Level,
    Modality,
    Provenance,
    Severity,
    SuccessCriterion,
)
from verity.report import (
    FINGERPRINT_KEY,
    SARIF_VERSION,
    CiPolicy,
    build_junit,
    build_sarif,
    load_policy,
    repo_relative_path,
    sarif_level,
    write_sarif,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def finding(
    provenance: Provenance = Provenance.AUTHORITATIVE,
    outcome: str = "fail",
    *,
    sc_id: str = "1.4.3",
    rule_id: str = "color-contrast",
    selector: str = "#hero",
    severity: Severity = Severity.SERIOUS,
    waived: bool = False,
    model: str | None = None,
) -> Finding:
    score = 1.0 if provenance is Provenance.AUTHORITATIVE else 0.0
    method = "deterministic" if provenance is Provenance.AUTHORITATIVE else "axe-incomplete"
    if provenance is Provenance.AI_ASSISTED:
        score, method, model = 0.7, "vision", model or "qwen2.5-vl-7b-4bit"

    f = Finding(
        id=f"{rule_id}-abc123abc123",
        rule_id=rule_id,
        sc=SuccessCriterion(
            id=sc_id, name="Contrast (Minimum)", level=Level.AA,
            modality=Modality.DETERMINISTIC,
        ),
        provenance=provenance,
        severity=severity,
        confidence=Confidence(score=score, method=method, model=model),
        agent="axe-core",
        outcome=outcome,
        message="Contrast 1.14:1 fails SC 1.4.3",
        evidence=Evidence(dom_selector=selector),
        page_state_hash="hash123",
    )
    if waived:
        f.waived = True
        f.evidence.computed_values["waiver"] = {
            "signature": "a" * 64,
            "justification": "Brand colours signed off by the design team.",
            "approved_by": "Design Lead",
            "created": "2026-08-17",
            "expires": "2027-08-17",
        }
    return f


def report(*findings: Finding, target: str = "https://example.com") -> AuditReport:
    return AuditReport(
        target=target,
        standard="WCAG2.2-AA",
        findings=list(findings),
        conformance={},
        verity_version="0.1.0",
        ruleset_version="1.0.0",
        latency=Latency(render_seconds=1.0, analysis_seconds=0.5, total_seconds=2.0),
    )


# --- B8.4: gating policy ---------------------------------------------------

def test_default_policy_fails_only_on_authoritative():
    policy = CiPolicy()
    assert policy.fail_on == "authoritative"
    assert policy.annotate_on == "ai_assisted"

    assert policy.gates(finding(Provenance.AUTHORITATIVE, "fail")) is True
    assert policy.gates(finding(Provenance.AI_ASSISTED, "fail")) is False
    assert policy.gates(finding(Provenance.NEEDS_REVIEW, "cantTell")) is False


def test_an_authoritative_pass_does_not_gate():
    """A pass is not a defect."""
    assert CiPolicy().gates(finding(Provenance.AUTHORITATIVE, "pass")) is False


def test_canttell_cannot_gate_from_any_direction():
    """
    "Only a `fail` gates" is enforced twice over, by two rules written in
    different weeks, and the overlap is worth pinning down:

    1. **B8.4** (here) refuses to gate anything whose outcome isn't `fail`.
    2. **B6.2** (`Finding`'s validator) makes an `AUTHORITATIVE` + `cantTell`
       finding *unconstructable* — you cannot be certain and undecided at
       once.

    So a `cantTell` can only ever carry `NEEDS_REVIEW`, which `fail_on:
    authoritative` already excludes. The first version of this test tried to
    build an authoritative `cantTell` to check rule 1 directly, and rule 2
    rejected it — the belt caught what the braces were for.
    """
    from pydantic import ValidationError

    # Rule 2: the combination does not exist.
    with pytest.raises(ValidationError, match="must be decided"):
        finding(Provenance.AUTHORITATIVE, "cantTell")

    # Rule 1: the only provenance a cantTell *can* carry doesn't gate anyway.
    undecided = finding(Provenance.NEEDS_REVIEW, "cantTell")
    assert CiPolicy().gates(undecided) is False
    # ...not even under the widest policy, because the outcome still isn't a fail.
    assert CiPolicy(fail_on="everything").gates(undecided) is False


def test_waived_findings_never_gate_but_still_annotate():
    """B7.2 and B8.4 agreeing: accepted, visible, not blocking."""
    waived = finding(waived=True)
    policy = CiPolicy()
    assert policy.gates(waived) is False
    assert policy.annotates(waived) is True


def test_report_only_mode_gates_nothing():
    """
    How a team adopts Verity on day one: see the real backlog before turning
    gating on deliberately.
    """
    policy = CiPolicy(fail_on="nothing", annotate_on="everything")
    assert policy.gating_findings([finding(), finding(Provenance.AI_ASSISTED)]) == []
    assert len(policy.annotated_findings([finding(), finding(Provenance.NEEDS_REVIEW, "cantTell")])) == 2


def test_levels_are_cumulative():
    """
    A stricter setting must never report *fewer* things — that would be a
    trap.
    """
    everything = CiPolicy(fail_on="everything")
    assert everything.gates(finding(Provenance.AUTHORITATIVE, "fail")) is True
    assert everything.gates(finding(Provenance.AI_ASSISTED, "fail")) is True


def test_unknown_gate_level_is_rejected():
    with pytest.raises(Exception, match="unknown gate level"):
        CiPolicy(fail_on="sometimes")


def test_gate_level_spelling_is_forgiving():
    assert CiPolicy(fail_on="AI-Assisted").fail_on == "ai_assisted"


def test_unknown_ci_key_is_rejected():
    """A typo'd key silently ignored would mean gating is on when a team thinks it is off."""
    with pytest.raises(Exception):
        CiPolicy(fail_on="authoritative", fail_onn="everything")


def test_policy_loads_from_a_config_file(tmp_path):
    cfg = tmp_path / "verity.yaml"
    cfg.write_text("ci:\n  fail_on: everything\n  annotate_on: everything\n", encoding="utf-8")
    assert load_policy(cfg).fail_on == "everything"


def test_missing_config_and_missing_ci_block_both_use_defaults(tmp_path):
    assert load_policy(None).fail_on == "authoritative"
    assert load_policy(tmp_path / "nope.yaml").fail_on == "authoritative"

    cfg = tmp_path / "verity.yaml"
    cfg.write_text("something_else: true\n", encoding="utf-8")
    assert load_policy(cfg).fail_on == "authoritative"


def test_bad_ci_block_raises_rather_than_defaulting(tmp_path):
    cfg = tmp_path / "verity.yaml"
    cfg.write_text("ci:\n  fail_on: whenever\n", encoding="utf-8")
    with pytest.raises(Exception):
        load_policy(cfg)


# --- B8.1: SARIF level tracks provenance, not severity --------------------

@pytest.mark.parametrize(
    "provenance,expected",
    [
        (Provenance.AUTHORITATIVE, "error"),
        (Provenance.AI_ASSISTED, "warning"),
        (Provenance.NEEDS_REVIEW, "note"),
    ],
)
def test_level_comes_from_provenance(provenance, expected):
    outcome = "cantTell" if provenance is Provenance.NEEDS_REVIEW else "fail"
    assert sarif_level(finding(provenance, outcome)) == expected


def test_a_critical_needs_review_finding_is_still_only_a_note():
    """
    The load-bearing case. SARIF `level` decides whether CI goes red, so it
    must track how much we trust the finding — not how bad the defect would
    be if it were real.
    """
    f = finding(Provenance.NEEDS_REVIEW, "cantTell", severity=Severity.CRITICAL)
    assert sarif_level(f) == "note"
    assert f.severity is Severity.CRITICAL


def test_severity_is_carried_in_properties_not_level():
    doc = build_sarif(report(finding(severity=Severity.CRITICAL)))
    result = doc["runs"][0]["results"][0]
    assert result["level"] == "error"
    assert result["properties"]["verity.severity"] == "critical"


# --- B8.1: document shape ------------------------------------------------

def test_sarif_has_the_fields_github_requires():
    doc = build_sarif(report(finding()))
    assert doc["version"] == SARIF_VERSION == "2.1.0"
    assert doc["$schema"]

    run = doc["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "Verity"
    assert driver["informationUri"]
    assert driver["rules"], "results reference rules by index; the array must exist"

    result = run["results"][0]
    for key in ("ruleId", "ruleIndex", "level", "message", "partialFingerprints"):
        assert key in result, f"GitHub needs {key}"
    assert result["message"]["text"]
    assert driver["rules"][result["ruleIndex"]]["id"] == result["ruleId"]


def test_rules_are_deduplicated_and_referenced_by_index():
    """A 300-finding report must not repeat the same rule description 300 times."""
    doc = build_sarif(report(
        finding(selector="#a"), finding(selector="#b"),
        finding(rule_id="image-alt", sc_id="1.1.1", selector="#c"),
    ))
    run = doc["runs"][0]
    assert len(run["tool"]["driver"]["rules"]) == 2
    assert len(run["results"]) == 3
    for result in run["results"]:
        assert run["tool"]["driver"]["rules"][result["ruleIndex"]]["id"] == result["ruleId"]


def test_annotate_on_controls_what_appears():
    rep = report(
        finding(Provenance.AUTHORITATIVE, "fail"),
        finding(Provenance.NEEDS_REVIEW, "cantTell"),
    )
    default = build_sarif(rep)
    everything = build_sarif(rep, policy=CiPolicy(annotate_on="everything"))

    assert len(default["runs"][0]["results"]) == 1, "needs-review omitted by default"
    assert len(everything["runs"][0]["results"]) == 2


def test_waived_findings_are_marked_suppressed_not_dropped():
    doc = build_sarif(report(finding(waived=True)))
    result = doc["runs"][0]["results"][0]
    assert result["suppressions"][0]["status"] == "accepted"
    assert "design team" in result["suppressions"][0]["justification"]


def test_sarif_is_json_serialisable():
    json.dumps(build_sarif(report(finding(), finding(Provenance.AI_ASSISTED))))


# --- B8.2: partialFingerprints -------------------------------------------

def test_fingerprint_matches_the_dedup_signature():
    """
    B8.2. Without this GitHub treats every alert as new on each run, "fixed"
    is never detected, and the same defect re-notifies forever.
    """
    from verity.agents.validator import signature_for

    f = finding()
    result = build_sarif(report(f))["runs"][0]["results"][0]
    assert result["partialFingerprints"][FINGERPRINT_KEY] == signature_for(f)


def test_fingerprint_key_is_versioned():
    """
    A7.1's stable-signature work changed the scheme (validator 3.0.0), so the
    key moved to /v2. A versioned key stops GitHub silently matching
    fingerprints computed two different ways across that change.
    """
    assert FINGERPRINT_KEY.endswith("/v2")


def test_fingerprint_is_stable_across_runs():
    a = build_sarif(report(finding()))["runs"][0]["results"][0]["partialFingerprints"]
    b = build_sarif(report(finding()))["runs"][0]["results"][0]["partialFingerprints"]
    assert a == b


# --- the URL-vs-file problem (docs/sarif-reference.md §5) -----------------

def test_a_remote_url_yields_no_inline_location():
    """
    Verity scans a URL; SARIF annotates a file. A remote page has no
    repo-relative path, so we emit no physicalLocation rather than invent
    one — a wrong `uri` annotates the wrong line of the wrong file, which is
    worse than no annotation.
    """
    assert repo_relative_path("https://example.com/pricing") is None

    doc = build_sarif(report(finding(), target="https://example.com/pricing"))
    run = doc["runs"][0]
    assert run["results"][0]["locations"] == []
    assert run["properties"]["verity.inlineAnnotationsPossible"] is False
    assert "noInlineAnnotationReason" in str(run["properties"])
    # The page must still be actionable from the Security tab.
    assert "https://example.com/pricing" in run["results"][0]["message"]["text"]


def test_a_local_file_in_the_repo_yields_a_relative_uri():
    fixture = REPO_ROOT / "data" / "fixtures" / "contrast-fail.html"
    target = fixture.as_uri()

    assert repo_relative_path(target) == "data/fixtures/contrast-fail.html"

    doc = build_sarif(report(finding(), target=target))
    run = doc["runs"][0]
    location = run["results"][0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "data/fixtures/contrast-fail.html"
    assert location["region"]["startLine"] == 1
    assert run["properties"]["verity.inlineAnnotationsPossible"] is True


def test_the_selector_is_kept_as_a_logical_location():
    """`#hero > p` is not a file position, but it is what a dev needs."""
    target = (REPO_ROOT / "data" / "fixtures" / "contrast-fail.html").as_uri()
    doc = build_sarif(report(finding(selector="#hero > p"), target=target))
    logical = doc["runs"][0]["results"][0]["locations"][0]["logicalLocations"][0]
    assert logical["name"] == "#hero > p"


def test_a_file_outside_the_repo_is_not_annotatable():
    assert repo_relative_path("file:///tmp/somewhere-else.html") is None


# --- B8.3: JUnit ---------------------------------------------------------

def test_junit_counts_only_gating_findings_as_failures():
    """
    A CI that fails on a non-zero failure count must agree with `verity
    scan`'s own exit code. Two different answers to "did this pass" is worse
    than either answer alone.
    """
    tree = build_junit(report(
        finding(Provenance.AUTHORITATIVE, "fail"),
        finding(Provenance.AI_ASSISTED, "fail"),
        finding(waived=True),
    ), policy=CiPolicy(annotate_on="everything"))

    suites = tree.getroot()
    assert suites.get("failures") == "1"
    suite = suites.find("testsuite")
    assert len(suite.findall("testcase/failure")) == 1
    assert len(suite.findall("testcase/skipped")) == 2


def test_junit_uses_skipped_for_non_gating_findings():
    """
    Every JUnit reader renders skips distinctly from passes and failures, and
    none fails a build on one. An `<error>` would go red; dropping them would
    hide needs-review findings from anyone not reading SARIF.
    """
    tree = build_junit(
        report(finding(Provenance.NEEDS_REVIEW, "cantTell")),
        policy=CiPolicy(annotate_on="everything"),
    )
    suite = tree.getroot().find("testsuite")
    assert suite.get("failures") == "0"
    skipped = suite.find("testcase/skipped")
    assert skipped is not None
    assert "needs review" in skipped.get("message")


def test_junit_groups_by_success_criterion():
    tree = build_junit(report(finding(sc_id="1.4.3")))
    case = tree.getroot().find("testsuite/testcase")
    assert case.get("classname") == "wcag.1.4.3"
    assert "color-contrast" in case.get("name")


def test_junit_passes_are_counted_but_silent():
    tree = build_junit(report(finding(outcome="pass")))
    suite = tree.getroot().find("testsuite")
    assert suite.get("tests") == "1"
    assert suite.get("failures") == "0"
    case = suite.find("testcase")
    assert list(case) == [], "a pass carries no failure or skip child"


def test_junit_failure_detail_is_actionable():
    tree = build_junit(report(finding()))
    text = tree.getroot().find("testsuite/testcase/failure").text
    for expected in ["success criterion", "severity", "provenance", "selector"]:
        assert expected in text


def test_junit_is_well_formed_xml(tmp_path):
    from verity.report import write_junit

    out = write_junit(report(finding(), finding(waived=True)), tmp_path / "junit.xml")
    parsed = ET.parse(out)
    assert parsed.getroot().tag == "testsuites"


def test_junit_notes_an_expired_waiver_rather_than_silently_reappearing():
    f = finding()
    f.evidence.computed_values["waiver_expired"] = {
        "signature": "a" * 64,
        "approved_by": "Design Lead",
        "justification": "Brand colours signed off by the design team.",
        "expired_on": "2026-01-01",
    }
    tree = build_junit(report(f))
    text = tree.getroot().find("testsuite/testcase/failure").text
    assert "expired on 2026-01-01" in text


# --- the committed sample SARIF -------------------------------------------
#
# `eval/fixtures/minimal.sarif.json` is a sample uploaded to a real repo by hand
# to confirm GitHub renders inline annotations (the half of the Week 8 artifact
# that needs a real PR — docs/sarif-reference.md §6). It is a COMMITTED fixture,
# so the test suite must not rewrite it: it used to, with a machine-local
# `file://` path baked into the target, which churned the tracked file on every
# run and on every contributor's machine. Now the target is a fixed, machine-
# independent string, the sample is built into a tmp dir for assertions, and a
# guard test keeps the committed copy current. Regenerate it deliberately with
# `python -m scripts.regen_sarif_sample` (or scripts/regen_sarif_sample.py).

SAMPLE_PATH = REPO_ROOT / "eval" / "fixtures" / "minimal.sarif.json"
# Fixed and machine-independent, so the committed fixture is byte-stable
# everywhere — never someone's absolute path.
SAMPLE_TARGET = "file:///verity/data/fixtures/contrast-fail.html"


def build_sample_sarif(out_path: Path) -> Path:
    """Build the sample SARIF at `out_path`. Shared by the test (tmp dir) and the
    regeneration script (the committed path), so the two can never diverge."""
    rep = report(
        finding(Provenance.AUTHORITATIVE, "fail", severity=Severity.CRITICAL),
        finding(Provenance.AI_ASSISTED, "fail", rule_id="image-alt", sc_id="1.1.1", selector="#logo"),
        finding(Provenance.NEEDS_REVIEW, "cantTell", selector="#over-image"),
        target=SAMPLE_TARGET,
    )
    return write_sarif(rep, out_path, policy=CiPolicy(annotate_on="everything"))


def test_sample_sarif_demonstrates_all_three_levels(tmp_path):
    out = build_sample_sarif(tmp_path / "minimal.sarif.json")   # tmp — never the tracked file
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["version"] == "2.1.0"
    levels = [r["level"] for r in doc["runs"][0]["results"]]
    assert levels == ["error", "warning", "note"], "the sample should demonstrate all three levels"


def test_sample_sarif_generation_is_deterministic(tmp_path):
    # If this ever fails, the committed fixture cannot be kept stable — there is
    # nondeterminism (a timestamp, unsorted output) to remove first.
    a = build_sample_sarif(tmp_path / "a.json").read_text(encoding="utf-8")
    b = build_sample_sarif(tmp_path / "b.json").read_text(encoding="utf-8")
    assert a == b


def test_committed_sample_sarif_is_current(tmp_path):
    # The tracked fixture must equal a fresh generation, so it never drifts and
    # never carries a machine path. The test does NOT write the tracked file.
    fresh = build_sample_sarif(tmp_path / "fresh.json").read_text(encoding="utf-8")
    assert SAMPLE_PATH.read_text(encoding="utf-8") == fresh, (
        "eval/fixtures/minimal.sarif.json is stale — regenerate it with "
        "`python scripts/regen_sarif_sample.py` and commit the result"
    )
