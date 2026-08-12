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

    assert exit_code == 0
    assert output_file.exists()

    # Verify report saved to disk matches expected JSON structure
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["target"] == "https://example.com"
    assert len(data["findings"]) == 1
    assert data["findings"][0]["sc"]["id"] == "1.4.3"


@pytest.mark.asyncio
async def test_run_cli_scan_invalid_url():
    exit_code = await run_cli_scan(url="", timeout=2.0)
    assert exit_code == 1