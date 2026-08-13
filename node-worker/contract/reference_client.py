"""
Reference client for the Verity Node worker — CONTRACT DEMONSTRATION ONLY.

This is not B1.2. It is the smallest possible thing that proves the contract is
real, so Engineer B can see the exact wire behaviour rather than reading a
description of it: a real render() against a local fixture, runAxe() against
the page it produced, and the resulting authoritative contrast finding. The
production client (verity/orchestrator/rpc_client.py) needs correlation by
id, per-call timeouts, typed exceptions, and clean shutdown — this has only
the first.

Run:  python3 contract/reference_client.py
"""

import asyncio
import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "dist" / "rpc" / "server.js"


async def main() -> None:
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(SERVER),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,  # keep separate: stderr is logs, not protocol
    )
    assert proc.stdin and proc.stdout

    async def call(request_id, method, params=None):
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params

        # One frame = one line. The newline IS the framing.
        proc.stdin.write((json.dumps(payload) + "\n").encode())
        await proc.stdin.drain()

        # readline() is safe because the worker guarantees no raw newline ever
        # appears inside a frame (JSON escapes them as \\n).
        line = await proc.stdout.readline()
        return json.loads(line)

    print("--- handshake ---")
    resp = await call(1, "ping")
    print(json.dumps(resp, indent=2))

    # A real client MUST verify this at startup, not on first use.
    assert resp["result"]["protocolVersion"] == 1, "protocol version mismatch"

    fixture = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "contrast-fail.html"
    print("\n--- render a real page ---")
    render_resp = await call(2, "render", {"url": fixture.as_uri()})
    print(json.dumps(render_resp, indent=2))

    print("\n--- runAxe against the page render() just produced ---")
    artifact_id = render_resp["result"]["artifactId"]
    axe_resp = await call(3, "runAxe", {"artifactId": artifact_id})
    contrast_findings = [v for v in axe_resp["result"]["violations"] if v["id"] == "color-contrast"]
    print(f"color-contrast violations found: {len(contrast_findings)}")
    if contrast_findings:
        print(json.dumps(contrast_findings[0], indent=2))

    print("\n--- param validation (expected: INVALID_PARAMS, -32602) ---")
    print(json.dumps(await call(4, "render", {}), indent=2))

    print("\n--- unknown method (expected: METHOD_NOT_FOUND, -32601) ---")
    print(json.dumps(await call(5, "totallyMadeUp"), indent=2))

    proc.stdin.close()
    await proc.wait()
    print("\nworker exited cleanly, code:", proc.returncode)


if __name__ == "__main__":
    if not SERVER.exists():
        sys.exit(f"build first: npm run build  (missing {SERVER})")
    asyncio.run(main())
