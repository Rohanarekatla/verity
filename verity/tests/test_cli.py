import json
import sys
from pathlib import Path
import pytest

from verity.cli import run_cli_scan


@pytest.mark.asyncio
async def test_run_cli_scan_success(tmp_path: Path):
    # Mock worker script that simulates Node worker stdout/stdin for 'render' and 'runAxe'
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
    output_file = tmp_path / "test_report.json"

    exit_code = await run_cli_scan(
        url="https://example.com",
        output_path=str(output_file),
        timeout=5.0,
        worker_cmd=cmd,
    )

    # B1.4: a page with authoritative findings must exit non-zero. The scan
    # itself succeeded — exit 1 here means "findings gate the build", not
    # "the tool crashed".
    assert exit_code == 1
    assert output_file.exists()

    # Verify report saved to disk matches expected JSON structure
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["target"] == "https://example.com"
    assert len(data["findings"]) == 1
    assert data["findings"][0]["sc"]["id"] == "1.4.3"


@pytest.mark.asyncio
async def test_run_cli_scan_clean_page_exits_zero(tmp_path: Path):
    """B1.4's other half: a clean page exits 0."""
    mock_worker_script = (
        "import sys, json; "
        "exec('while True:\\n"
        "  line = sys.stdin.readline()\\n"
        "  if not line: break\\n"
        "  req = json.loads(line)\\n"
        "  m = req.get(\"method\")\\n"
        "  res = {\"jsonrpc\": \"2.0\", \"id\": req[\"id\"]}\\n"
        "  res[\"result\"] = {\"artifactId\": \"art-123\", \"page_state\": {\"content_hash\": \"abc1234\"}} if m == \"render\" else {\"violations\": []}\\n"
        "  print(json.dumps(res))\\n"
        "  sys.stdout.flush()\\n')"
    )

    exit_code = await run_cli_scan(
        url="https://example.com",
        timeout=5.0,
        worker_cmd=[sys.executable, "-c", mock_worker_script],
    )
    assert exit_code == 0


@pytest.mark.asyncio
async def test_best_practice_rules_do_not_become_wcag_findings(tmp_path: Path):
    """
    axe's `best-practice` rules (region, landmark-one-main) carry no WCAG
    success-criterion tag. Reporting them as authoritative WCAG failures is a
    false positive, so they must be excluded from the conformance report --
    and a page whose only findings are best-practice must exit 0.
    """
    mock_worker_script = (
        "import sys, json; "
        "exec('while True:\\n"
        "  line = sys.stdin.readline()\\n"
        "  if not line: break\\n"
        "  req = json.loads(line)\\n"
        "  m = req.get(\"method\")\\n"
        "  res = {\"jsonrpc\": \"2.0\", \"id\": req[\"id\"]}\\n"
        "  res[\"result\"] = {\"artifactId\": \"art-123\", \"page_state\": {\"content_hash\": \"abc1234\"}} if m == \"render\" else {\"violations\": [{\"id\": \"region\", \"tags\": [\"cat.keyboard\", \"best-practice\"], \"help\": \"All content should be contained by landmarks\", \"impact\": \"moderate\", \"selector\": \"h1\"}]}\\n"
        "  print(json.dumps(res))\\n"
        "  sys.stdout.flush()\\n')"
    )

    output_file = tmp_path / "bp.json"
    exit_code = await run_cli_scan(
        url="https://example.com",
        output_path=str(output_file),
        timeout=5.0,
        worker_cmd=[sys.executable, "-c", mock_worker_script],
    )

    assert exit_code == 0, "a best-practice-only page must not fail the build"
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["findings"] == [], "best-practice rules must not be emitted as WCAG findings"


@pytest.mark.asyncio
async def test_write_baseline_flag_records_findings(tmp_path: Path):
    """A8.3: --write-baseline records the scan's findings as a loadable,
    content-addressed baseline. The Action's baseline workflow depends on it."""
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
    baseline_file = tmp_path / "baseline.json"

    await run_cli_scan(
        url="https://example.com",
        timeout=5.0,
        worker_cmd=[sys.executable, "-c", mock_worker_script],
        write_baseline_path=str(baseline_file),
    )

    assert baseline_file.exists()
    from verity.report.baseline import load_baseline  # also re-verifies the content address

    baseline = load_baseline(baseline_file)
    assert len(baseline.entries) == 1
    assert baseline.entries[0].sc_id == "1.4.3"


@pytest.mark.asyncio
async def test_run_cli_scan_invalid_url():
    """A scan that could not run exits 2, never 1: 1 means "gating findings"."""
    exit_code = await run_cli_scan(url="", timeout=2.0)
    assert exit_code == 2


def test_local_paths_become_file_urls(tmp_path):
    from verity.cli import normalize_target

    page = tmp_path / "index.html"
    page.write_text("<!doctype html><title>t</title>")
    assert normalize_target(str(page)) == page.resolve().as_uri()
    assert normalize_target("https://example.com") == "https://example.com"
    assert normalize_target("file:///x.html") == "file:///x.html"
    # Not a URL and not an existing file: passed through, so the error names it.
    assert normalize_target("no-such-page.html") == "no-such-page.html"
    # A directory is not a page.
    assert normalize_target(str(tmp_path)) == str(tmp_path)
    assert normalize_target("") == ""