"""
A15.1′ — the Verity MCP server: catalog, validation, dispatch, protocol.

Proves the tool catalog is well-formed and agent-friendly (schemas + idempotency
hints), bad arguments produce a readable error result rather than an exception,
the stdio protocol answers initialize/tools/list/tools/call, and the pure
explain-a-finding logic (including which tool confirms each fix) is correct.
"""

from verity.mcp import TOOLS, call_tool, list_tools
from verity.mcp.capabilities import confirm_tool_for, explain_finding
from verity.mcp.server import handle_message
from verity.mcp.tools import ToolError


class FakeCaps:
    """Records calls; returns small dicts."""

    def __init__(self):
        self.calls = []

    def scan(self, url, *, config=None):
        self.calls.append(("scan", url))
        return {"target": url, "finding_count": 0, "findings": []}

    def explain_finding(self, report, finding_id):
        return explain_finding(report, finding_id)

    def sample_contrast(self, url, selector):
        return {"url": url, "family": "contrast", "findings": []}

    def traverse(self, url):
        return {"url": url, "findings": []}

    def run_contract(self, url, selector=None):
        return {"url": url, "findings": []}

    def virtual_sr_read(self, url):
        return {"url": url, "findings": []}

    def baseline_diff(self, url, baseline_path, *, config=None):
        return {"url": url, "regression_free": True}


# --- catalog ---------------------------------------------------------------

def test_catalog_is_agent_friendly():
    names = {t.name for t in TOOLS}
    assert names == {"scan", "explain_finding", "sample_contrast", "traverse",
                     "run_contract", "virtual_sr_read", "baseline_diff"}
    for t in TOOLS:
        assert t.input_schema["type"] == "object"
        assert "properties" in t.input_schema and "required" in t.input_schema
    # Only scan mutates / renders; everything else is a safe, idempotent read.
    assert {t.name for t in TOOLS if not t.idempotent} == {"scan"}


def test_tools_list_payload_has_schemas_and_hints():
    listed = {t["name"]: t for t in list_tools()}
    assert listed["scan"]["annotations"]["idempotentHint"] is False
    assert listed["traverse"]["annotations"]["readOnlyHint"] is True
    assert "inputSchema" in listed["explain_finding"]


# --- dispatch & validation -------------------------------------------------

def test_call_tool_dispatches_and_wraps_result():
    caps = FakeCaps()
    res = call_tool("scan", {"url": "http://x"}, caps)
    assert res["isError"] is False
    assert res["structuredContent"]["target"] == "http://x"
    assert caps.calls == [("scan", "http://x")]


def test_missing_required_argument_is_a_readable_error():
    res = call_tool("sample_contrast", {"url": "http://x"}, FakeCaps())  # no selector
    assert res["isError"] is True
    assert "selector" in res["content"][0]["text"]


def test_unknown_argument_rejected():
    res = call_tool("scan", {"url": "http://x", "bogus": 1}, FakeCaps())
    assert res["isError"] is True and "bogus" in res["content"][0]["text"]


def test_unknown_tool_is_an_error_not_a_crash():
    res = call_tool("nope", {}, FakeCaps())
    assert res["isError"] is True and "unknown tool" in res["content"][0]["text"]


def test_capability_exception_becomes_error_result():
    class Boom(FakeCaps):
        def traverse(self, url):
            raise RuntimeError("worker down")

    res = call_tool("traverse", {"url": "http://x"}, Boom())
    assert res["isError"] is True and "worker down" in res["content"][0]["text"]


# --- protocol --------------------------------------------------------------

def test_initialize_and_tools_list():
    init = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, FakeCaps())
    assert init["result"]["serverInfo"]["name"] == "verity"
    assert "protocolVersion" in init["result"]

    listed = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, FakeCaps())
    assert len(listed["result"]["tools"]) == len(TOOLS)


def test_tools_call_over_protocol():
    msg = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
           "params": {"name": "scan", "arguments": {"url": "http://x"}}}
    resp = handle_message(msg, FakeCaps())
    assert resp["result"]["isError"] is False


def test_notification_gets_no_reply_and_unknown_method_errors():
    assert handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, FakeCaps()) is None
    err = handle_message({"jsonrpc": "2.0", "id": 9, "method": "frobnicate"}, FakeCaps())
    assert err["error"]["code"] == -32601


# --- explain_finding (pure) ------------------------------------------------

def _report():
    return {"findings": [{
        "id": "f1", "provenance": "needs review", "outcome": "cantTell",
        "message": "button has no accessible name",
        "sc": {"id": "4.1.2", "name": "Name, Role, Value", "level": "A"},
        "evidence": {"dom_selector": "#submit"},
    }]}


def test_explain_finding_returns_fix_and_confirm_tool():
    out = explain_finding(_report(), "f1")
    assert out["sc"] == "4.1.2" and out["selector"] == "#submit"
    assert out["confirm_with"] == "run_contract"      # the tool that confirms 4.1.2
    assert "accessible name" in out["remediation"]


def test_explain_unknown_finding_raises_tool_error():
    import pytest

    with pytest.raises(ToolError):
        explain_finding(_report(), "nope")


def test_confirm_tool_mapping():
    assert confirm_tool_for("1.4.3") == "sample_contrast"
    assert confirm_tool_for("2.1.1") == "traverse"
    assert confirm_tool_for("9.9.9") == "scan"       # unknown -> a full scan
