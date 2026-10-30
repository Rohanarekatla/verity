"""
A15.1′ — the MCP tool catalog, input validation, and dispatch.

The catalog is the contract a coding agent (the fix loop, B15.1′) codes
against, so it is designed for one: every tool has a JSON-Schema input, a small
structured output, and an idempotency flag, because an agent that cannot predict
whether a call is safe to retry will either loop or give up. Only `scan` does
real work; everything else is a pure read over a scan it was already given, so
the agent can interrogate a result without re-rendering the page.

The handlers live behind a `Capabilities` seam: `call_tool` validates the
arguments against the schema and dispatches to the capability, so the catalog
and the dispatch are tested with a fake capability object — no browser, no
network — and the real wiring (`default_capabilities`) is a thin adapter over
`scan_url`, the contrast sampler, the traversal, the contract runner, the
virtual screen reader, and the baseline diff.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol


class ToolError(Exception):
    """A tool call that could not run — bad arguments, or a capability failure.
    Reported to the agent as an MCP error result, never raised across stdio."""


# -- the capability seam ------------------------------------------------------

class Capabilities(Protocol):
    """What the tools need from Verity. The real one wraps the engine; tests
    pass a fake. Each returns a small JSON-able dict."""

    def scan(self, url: str, *, config: Optional[str] = None) -> dict: ...
    def explain_finding(self, report: dict, finding_id: str) -> dict: ...
    def sample_contrast(self, url: str, selector: str) -> dict: ...
    def traverse(self, url: str) -> dict: ...
    def run_contract(self, url: str, selector: Optional[str] = None) -> dict: ...
    def virtual_sr_read(self, url: str) -> dict: ...
    def baseline_diff(self, url: str, baseline_path: str, *, config: Optional[str] = None) -> dict: ...


# -- the catalog --------------------------------------------------------------

_URL = {"type": "string", "description": "URL or local HTML file path"}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: str          # the Capabilities method name
    idempotent: bool      # safe for an agent to retry without side effects

    def to_mcp(self) -> dict:
        """The `tools/list` entry, with the idempotency hint in annotations."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"readOnlyHint": self.idempotent, "idempotentHint": self.idempotent},
        }


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOLS: tuple[Tool, ...] = (
    Tool(
        "scan",
        "Run Verity's full deterministic scan on a page; returns findings with provenance. "
        "The one tool that renders the page — use it once, then interrogate the result with the others.",
        _schema({"url": _URL, "config": {"type": "string", "description": "optional config path (ci policy)"}},
                ["url"]),
        handler="scan", idempotent=False,
    ),
    Tool(
        "explain_finding",
        "Explain one finding from a scan result: its success criterion, why it fails, how to fix it, "
        "and its evidence. Pure — reads the report you pass, renders nothing.",
        _schema({"report": {"type": "object", "description": "an AuditReport JSON from scan"},
                 "finding_id": {"type": "string"}}, ["report", "finding_id"]),
        handler="explain_finding", idempotent=True,
    ),
    Tool(
        "sample_contrast",
        "Sample the worst-case contrast ratio of a text element from its rendered pixels. "
        "The model localises, the maths decides — this returns the measured ratio, not a judgement.",
        _schema({"url": _URL, "selector": {"type": "string", "description": "CSS selector of the text element"}},
                ["url", "selector"]),
        handler="sample_contrast", idempotent=True,
    ),
    Tool(
        "traverse",
        "Drive the page by keyboard and report the tab order, any trap, and focus visibility. "
        "Confirms a keyboard fix (SC 2.1.1/2.1.2/2.4.7).",
        _schema({"url": _URL}, ["url"]),
        handler="traverse", idempotent=True,
    ),
    Tool(
        "run_contract",
        "Run the APG contract for the widget(s) at `selector` (or every recognised widget): drive the "
        "keys, check the announced transitions. Confirms an ARIA/interaction fix.",
        _schema({"url": _URL, "selector": {"type": "string", "description": "optional widget selector"}},
                ["url"]),
        handler="run_contract", idempotent=True,
    ),
    Tool(
        "virtual_sr_read",
        "Read the page with the virtual screen reader: the ordered announcements a screen-reader user "
        "would hear. Confirms a name/role/announcement fix.",
        _schema({"url": _URL}, ["url"]),
        handler="virtual_sr_read", idempotent=True,
    ),
    Tool(
        "baseline_diff",
        "Scan the page and diff against a baseline: which findings are new, fixed, or unchanged. "
        "This is the regression gate — a fix is accepted only if it introduces no new finding.",
        _schema({"url": _URL, "baseline_path": {"type": "string"},
                 "config": {"type": "string", "description": "optional config path"}},
                ["url", "baseline_path"]),
        handler="baseline_diff", idempotent=True,
    ),
)

TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def list_tools() -> list[dict]:
    """The `tools/list` payload."""
    return [t.to_mcp() for t in TOOLS]


# -- a minimal input validator (no jsonschema dependency) ---------------------

_PY_TYPE = {"string": str, "object": dict, "number": (int, float), "integer": int,
            "boolean": bool, "array": list}


def _validate(tool: Tool, args: dict) -> None:
    schema = tool.input_schema
    if not isinstance(args, dict):
        raise ToolError(f"{tool.name}: arguments must be an object")
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise ToolError(f"{tool.name}: missing required argument(s): {', '.join(missing)}")
    props = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = [k for k in args if k not in props]
        if extra:
            raise ToolError(f"{tool.name}: unknown argument(s): {', '.join(extra)}")
    for key, value in args.items():
        spec = props.get(key)
        if spec and "type" in spec and not isinstance(value, _PY_TYPE.get(spec["type"], object)):
            raise ToolError(f"{tool.name}: argument {key!r} must be a {spec['type']}")


# -- dispatch -----------------------------------------------------------------

def call_tool(name: str, arguments: dict, caps: Capabilities) -> dict:
    """
    Validate `arguments` against the tool's schema and dispatch to `caps`.
    Always returns an MCP tool result (`content` + `isError`) — a bad call is an
    error result the agent can read and correct, never an exception over stdio.
    """
    import json

    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return _error(f"unknown tool {name!r}; known: {', '.join(TOOLS_BY_NAME)}")
    try:
        _validate(tool, arguments)
        handler: Callable = getattr(caps, tool.handler)
        result = handler(**arguments)
    except ToolError as exc:
        return _error(str(exc))
    except Exception as exc:  # a capability failure is an error result, not a crash
        return _error(f"{name} failed: {exc.__class__.__name__}: {exc}")
    return {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
        "structuredContent": result,
        "isError": False,
    }


def _error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}
