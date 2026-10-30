"""
A15.1′ — the Verity MCP server.

Verity's deterministic checks, exposed as MCP tools a coding agent can call to
*confirm* a fix: scan, explain a finding, sample contrast, traverse by keyboard,
run an APG contract, read the virtual screen reader, diff against a baseline.
This is the verifier half of verifier-gated remediation (the fix loop, B15.1′,
is the coding agent that calls these and accepts a patch only when Verity proves
the defect gone and no regression).

Tool design follows the week's learning (small, typed, idempotent): every tool
has a JSON-Schema input, returns a small structured result, and — except `scan`,
which is the one that does real work — is a pure read a coding agent can call
repeatedly without side effects.
"""

from verity.mcp.tools import (
    TOOLS,
    Capabilities,
    ToolError,
    call_tool,
    list_tools,
)

__all__ = ["TOOLS", "Capabilities", "ToolError", "call_tool", "list_tools"]
