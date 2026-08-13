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