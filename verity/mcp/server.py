"""
A15.1′ — the MCP stdio server loop.

Line-delimited JSON-RPC 2.0 over stdin/stdout — the same framing the Node worker
uses (one JSON object per line), and the transport MCP clients speak by default.
`handle_message` is pure (message in, response out or None for a notification)
so the protocol is tested without pipes; `serve` is the thin read/parse/write
loop around it.

Only the three methods an MCP tool server needs are implemented — `initialize`,
`tools/list`, `tools/call` — plus the `notifications/initialized` the client
sends after initialising, which is acknowledged by silence. Anything else gets a
proper JSON-RPC "method not found" so a client fails loudly, not mysteriously.
"""

from __future__ import annotations

import json
import sys
from typing import Optional

from verity.mcp.tools import Capabilities, call_tool, list_tools

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "verity", "version": "0.1.0"}


def _result(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle_message(msg: dict, caps: Capabilities) -> Optional[dict]:
    """
    Handle one JSON-RPC message. Returns the response, or None for a
    notification (no `id`) that needs no reply.
    """
    mid = msg.get("id")
    method = msg.get("method")

    if method == "initialize":
        return _result(mid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(mid, {"tools": list_tools()})
    if method == "tools/call":
        params = msg.get("params") or {}
        return _result(mid, call_tool(params.get("name"), params.get("arguments") or {}, caps))

    if mid is None:
        return None  # an unknown notification: ignore, per JSON-RPC
    return _error(mid, -32601, f"method not found: {method}")


def serve(caps: Capabilities, *, stdin=None, stdout=None) -> None:
    """Read JSON-RPC messages line by line and write responses. Blocks until EOF."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _write(stdout, _error(None, -32700, "parse error: invalid JSON"))
            continue
        response = handle_message(msg, caps)
        if response is not None:
            _write(stdout, response)


def _write(stream, obj: dict) -> None:
    stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
    stream.flush()


def main() -> int:
    from verity.mcp.capabilities import default_capabilities

    serve(default_capabilities())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
