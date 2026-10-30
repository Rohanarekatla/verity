"""
A16.1′ — WebMCP readiness checks.

Three checks, the agent-readiness analogue of a conformance scan:

1. **Registered tools** — does the page declare any WebMCP tools at all? Without
   them an agent must scrape the DOM, which is the problem WebMCP exists to fix.
2. **Form coverage** — is every data-bearing form driven by a tool? A form is
   covered when a tool is bound to it (matching selector) or a tool's schema is
   sufficient-and-safe for it (`verify_tool_against_form`). An uncovered form is
   a gap: an agent cannot reliably submit it.
3. **Schema validity** — is each tool's `input_schema` a well-formed JSON-Schema
   object with typed properties? An invalid schema is a tool an agent cannot
   call.

The score is honest: coverage drives it, invalid schemas penalise it, and a page
with no forms to cover is not marked down for declaring no tools — it says so in
an info note instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from verity.webmcp.generator import verify_tool_against_form
from verity.webmcp.model import FormModel, WebMcpPage, WebMcpTool


@dataclass
class ReadinessIssue:
    code: str
    level: str            # error | warning | info
    message: str
    selector: Optional[str] = None


@dataclass
class ReadinessReport:
    url: str
    tool_count: int
    form_count: int
    covered: list[str] = field(default_factory=list)       # form selectors covered
    uncovered: list[str] = field(default_factory=list)     # form selectors not covered
    invalid_schemas: list[str] = field(default_factory=list)  # tool names
    issues: list[ReadinessIssue] = field(default_factory=list)
    score: int = 0

    @property
    def ready(self) -> bool:
        return not self.uncovered and not self.invalid_schemas


def _valid_schema(schema: dict) -> bool:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    props = schema.get("properties")
    if not isinstance(props, dict) or not props:
        return False
    return all(isinstance(p, dict) and ("type" in p or "enum" in p) for p in props.values())


def _covers(tool: WebMcpTool, form: FormModel) -> bool:
    if tool.form_selector and tool.form_selector == form.selector:
        return True
    return verify_tool_against_form(tool, form).ok


def check_readiness(page: WebMcpPage) -> ReadinessReport:
    """Run the three readiness checks and score the page."""
    tools = page.tools
    meaningful = [f for f in page.forms if f.fields]
    report = ReadinessReport(url=page.url, tool_count=len(tools), form_count=len(meaningful))

    # 2/3: validity, computed first so an invalid tool cannot "cover" a form.
    valid_tools: list[WebMcpTool] = []
    for t in tools:
        if _valid_schema(t.input_schema):
            valid_tools.append(t)
        else:
            report.invalid_schemas.append(t.name)
            report.issues.append(ReadinessIssue(
                "invalid-schema", "error",
                f"tool {t.name!r} has an invalid input schema; an agent cannot call it"))

    # 1: registered tools.
    if not tools:
        if meaningful:
            report.issues.append(ReadinessIssue(
                "no-webmcp-tools", "error",
                "page declares no WebMCP tools; an agent must scrape the DOM to use its forms"))
        else:
            report.issues.append(ReadinessIssue(
                "no-webmcp-tools", "info",
                "no WebMCP tools and no data-bearing forms — nothing for an agent to drive"))

    # 2: coverage.
    for form in meaningful:
        if any(_covers(t, form) for t in valid_tools):
            report.covered.append(form.selector)
        else:
            report.uncovered.append(form.selector)
            report.issues.append(ReadinessIssue(
                "form-not-covered", "warning",
                f"form {form.selector} has no WebMCP tool an agent can use to submit it",
                selector=form.selector))

    report.score = _score(meaningful, report)
    return report


def _score(meaningful: list[FormModel], report: ReadinessReport) -> int:
    if not meaningful:
        # Nothing to cover: ready unless a declared tool is malformed.
        return 100 if not report.invalid_schemas else max(0, 100 - 20 * len(report.invalid_schemas))
    coverage = len(report.covered) / len(meaningful)
    score = round(100 * coverage) - 15 * len(report.invalid_schemas)
    return max(0, min(100, score))
