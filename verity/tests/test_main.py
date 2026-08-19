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
# --- finding identity ---

def test_finding_id_is_reproducible_across_processes():
    """
    Ids must be identical on every run of an unchanged page. Built on
    `hash()` they were not: CPython salts string hashing per process, so the
    same selector produced a different id each run and every report diff was
    noise. Subprocess, because that is the only way to observe the salt.
    """
    import os
    import subprocess
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo_root)}
    env.pop("PYTHONHASHSEED", None)  # do not let a pinned seed hide the bug

    snippet = (
        "from verity.orchestrator.main import derive_finding_id; "
        "print(derive_finding_id('color-contrast', 'button.btn > span'))"
    )
    runs = {
        subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, check=True, env=env, cwd=repo_root,
        ).stdout.strip()
        for _ in range(3)
    }
    assert len(runs) == 1, f"finding id is not stable across processes: {runs}"


def test_finding_id_distinguishes_rule_and_selector():
    from verity.orchestrator.main import derive_finding_id

    a = derive_finding_id("color-contrast", "#a")
    assert a != derive_finding_id("color-contrast", "#b")
    assert a != derive_finding_id("image-alt", "#a")
    assert a.startswith("color-contrast-")


def test_finding_carries_the_raw_rule_id():
    """dedup needs the rule; recovering it by splitting `id` was fragile."""
    finding = map_raw_violation_to_finding(
        {"id": "color-contrast", "tags": ["wcag143"], "selector": "#btn"},
        page_state_hash="h",
    )
    assert finding.rule_id == "color-contrast"


# --- conformance map ---

def test_conformance_keeps_the_worst_outcome_per_criterion():
    """
    Both `color-contrast` buckets map to SC 1.4.3, and incomplete items are
    appended after violations. Last-write-wins let an undecided `cantTell`
    overwrite a proven `fail`, understating a real conformance failure.
    """
    from verity.orchestrator.main import build_conformance_map
    from verity.agents.contrast import flag_needs_review

    failed = map_raw_violation_to_finding(
        {"id": "color-contrast", "tags": ["wcag143"], "selector": "#a", "impact": "serious"},
        page_state_hash="h",
    )
    undecided = flag_needs_review(
        map_raw_violation_to_finding(
            {"id": "color-contrast", "tags": ["wcag143"], "selector": "#b", "impact": "serious"},
            page_state_hash="h",
        )
    )

    assert build_conformance_map([failed, undecided])["1.4.3"] == "fail"
    assert build_conformance_map([undecided, failed])["1.4.3"] == "fail"
    assert build_conformance_map([undecided])["1.4.3"] == "cantTell"


def test_conformance_excludes_waived_findings():
    """A waiver is an accepted failure; it must clear the criterion."""
    from verity.orchestrator.main import build_conformance_map

    finding = map_raw_violation_to_finding(
        {"id": "color-contrast", "tags": ["wcag143"], "selector": "#a"},
        page_state_hash="h",
    )
    finding.waived = True
    assert build_conformance_map([finding]) == {}


# --- pipeline guards ---

@pytest.mark.asyncio
async def test_render_without_content_hash_fails_loudly():
    """
    page_state_hash is the join key for baselining. Defaulting it to a
    placeholder made every finding on every page share one fabricated state.
    """
    script = (
        "import sys, json\n"
        "while True:\n"
        "    line = sys.stdin.readline()\n"
        "    if not line: break\n"
        "    req = json.loads(line)\n"
        "    res = {'jsonrpc': '2.0', 'id': req['id'], 'result': {'artifactId': 'a1'}}\n"
        "    print(json.dumps(res)); sys.stdout.flush()\n"
    )
    with pytest.raises(ValueError, match="page_state.content_hash"):
        await scan_url(
            "https://example.com",
            node_worker_command=[sys.executable, "-c", script],
            timeout=5.0,
        )


@pytest.mark.asyncio
async def test_untagged_incomplete_contrast_is_skipped_not_fatal():
    """
    The violations loop guards against rules with no WCAG tag; the incomplete
    loop did not, so a retagged axe release would abort the whole scan
    instead of dropping one node.
    """
    script = (
        "import sys, json\n"
        "while True:\n"
        "    line = sys.stdin.readline()\n"
        "    if not line: break\n"
        "    req = json.loads(line)\n"
        "    m = req.get('method')\n"
        "    if m == 'render':\n"
        "        r = {'artifactId': 'a1', 'page_state': {'content_hash': 'abc'}}\n"
        "    else:\n"
        "        r = {'violations': [], 'incomplete': ["
        "            {'id': 'color-contrast', 'tags': ['best-practice'], 'selector': '#x'}"
        "        ]}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': r}))\n"
        "    sys.stdout.flush()\n"
    )
    report = await scan_url(
        "https://example.com",
        node_worker_command=[sys.executable, "-c", script],
        timeout=5.0,
    )
    assert report.findings == []


# --- B2.5 latency ---

@pytest.mark.asyncio
async def test_report_records_latency():
    """
    Week 2's latency gate needs a number in the report. It used to exist only
    as a logger.info line, which default logging levels discard.
    """
    script = (
        "import sys, json\n"
        "while True:\n"
        "    line = sys.stdin.readline()\n"
        "    if not line: break\n"
        "    req = json.loads(line)\n"
        "    m = req.get('method')\n"
        "    r = ({'artifactId': 'a1', 'page_state': {'content_hash': 'abc'}}\n"
        "         if m == 'render' else {'violations': [], 'incomplete': []})\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': r}))\n"
        "    sys.stdout.flush()\n"
    )
    report = await scan_url(
        "https://example.com",
        node_worker_command=[sys.executable, "-c", script],
        timeout=5.0,
    )

    assert report.latency is not None
    assert report.latency.total_seconds > 0
    assert report.latency.render_seconds >= 0
    assert report.latency.analysis_seconds >= 0
    # The phases are parts of the whole, not independent measurements.
    assert (
        report.latency.render_seconds + report.latency.analysis_seconds
        <= report.latency.total_seconds + 1e-6
    )
    # And it must survive serialisation — the gate reads the JSON report.
    assert AuditReport.model_validate_json(report.model_dump_json()).latency == report.latency
