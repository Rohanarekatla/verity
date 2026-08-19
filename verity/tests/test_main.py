import sys
import pytest
from verity.orchestrator.main import scan_url, map_raw_violation_to_finding
from verity.models.schemas import AuditReport, Provenance, Severity


def test_map_raw_violation_to_finding():
    raw = {
        "id": "image-alt",
        "tags": ["wcag111"],
        "help": "Images must have alternate text",
        "impact": "critical",
        "description": "Img element missing alt attribute",
        "selector": "img#hero-banner",
        "html": '<img id="hero-banner" src="/hero.png">',
        "helpUrl": "https://dequeuniversity.com/rules/axe/4.4/image-alt",
        "failureSummary": "Fix any of the following: Element does not have an alt attribute",
    }

    finding = map_raw_violation_to_finding(raw, page_state_hash="hash123")

    assert finding.sc.id == "1.1.1"
    assert finding.provenance == Provenance.AUTHORITATIVE
    assert finding.severity == Severity.CRITICAL
    assert finding.evidence.dom_selector == "img#hero-banner"
    assert finding.evidence.computed_values["html"] == '<img id="hero-banner" src="/hero.png">'
    assert finding.page_state_hash == "hash123"


@pytest.mark.asyncio
async def test_scan_url_pipeline_integration():
    # Single-line mock worker script formatted for python -c execution on Windows
    mock_worker_script = (
        "import sys, json; "
        "exec('while True:\\n"
        "  line = sys.stdin.readline()\\n"
        "  if not line: break\\n"
        "  req = json.loads(line)\\n"
        "  m = req.get(\"method\")\\n"
        "  res = {\"jsonrpc\": \"2.0\", \"id\": req[\"id\"]}\\n"
        "  res[\"result\"] = {\"artifactId\": \"art-123\", \"page_state\": {\"content_hash\": \"abc1234\"}} if m == \"render\" else {\"violations\": [{\"id\": \"color-contrast\", \"tags\": [\"wcag143\"], \"help\": \"Low contrast\", \"impact\": \"serious\", \"selector\": \"#btn\", \"description\": \"Text contrast below 4.5:1\"}]}\\n"
        "  print(json.dumps(res))\\n"
        "  sys.stdout.flush()\\n')"
    )

    cmd = [sys.executable, "-c", mock_worker_script]
    report: AuditReport = await scan_url("https://example.com", node_worker_command=cmd, timeout=5.0)

    assert report.target == "https://example.com"
    assert len(report.findings) == 1

    finding = report.findings[0]
    assert finding.sc.id == "1.4.3"
    assert finding.provenance == Provenance.AUTHORITATIVE
    assert finding.severity == Severity.SERIOUS
    assert finding.agent == "axe-core"

# --- WCAG success-criterion tag extraction ---

def test_extract_sc_id_parses_criterion_tags():
    from verity.orchestrator.main import extract_sc_id

    assert extract_sc_id(["cat.color", "wcag2aa", "wcag143", "ACT"]) == "1.4.3"
    assert extract_sc_id(["wcag111"]) == "1.1.1"


def test_extract_sc_id_ignores_level_and_category_tags():
    """
    Level tags (wcag2a/wcag2aa/wcag22aa) and category tags are not criterion
    references. Parsing them as one is how a rule gets attributed to the
    wrong success criterion.
    """
    from verity.orchestrator.main import extract_sc_id

    assert extract_sc_id(["wcag2a"]) is None
    assert extract_sc_id(["wcag2aa"]) is None
    assert extract_sc_id(["wcag22aa"]) is None
    assert extract_sc_id(["cat.semantics", "EN-301-549", "RGAAv4"]) is None


def test_extract_sc_id_returns_none_for_best_practice_rules():
    """axe best-practice rules map to no success criterion at all."""
    from verity.orchestrator.main import extract_sc_id

    assert extract_sc_id(["cat.semantics", "best-practice"]) is None
    assert extract_sc_id(["cat.keyboard", "best-practice", "RGAA-9.2.1"]) is None
    assert extract_sc_id([]) is None
    assert extract_sc_id(None) is None


def test_mapping_refuses_to_invent_a_criterion():
    """
    Mapping a rule with no WCAG tag must raise rather than silently default.
    A fabricated SC becomes an authoritative false positive downstream.
    """
    import pytest as _pytest
    from verity.orchestrator.main import map_raw_violation_to_finding

    with _pytest.raises(ValueError, match="no WCAG success-criterion tag"):
        map_raw_violation_to_finding(
            {"id": "region", "tags": ["best-practice"], "selector": "h1"},
            page_state_hash="abc",
        )


# --- Week 1 gate regression guard ---
#
# The shipped default waivers.yaml must not suppress the gate fixture. A
# waiver committed against a test fixture once made this exit 0 instead of
# 1 (the finding was produced correctly but flagged waived), silently
# defeating the gate. This pins the end-to-end behaviour so it can't
# regress again without a red test.

@pytest.mark.asyncio
async def test_week1_gate_fixture_is_authoritative_and_not_waived():
    import pathlib
    from verity.models.schemas import Provenance

    fixture = (
        pathlib.Path(__file__).resolve().parents[2]
        / "data" / "fixtures" / "contrast-fail.html"
    )
    report = await scan_url(fixture.as_uri(), timeout=60.0)

    contrast = [f for f in report.findings if f.sc.id == "1.4.3"]
    assert len(contrast) == 1, f"expected one 1.4.3 finding, got {len(contrast)}"

    f = contrast[0]
    assert f.provenance is Provenance.AUTHORITATIVE
    assert f.outcome == "fail"
    assert f.waived is False, (
        "the gate fixture must not be waived by the default config — "
        "a waiver targeting a test fixture defeats the Week 1 gate"
    )
