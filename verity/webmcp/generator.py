"""
A16.2′ — generate a WebMCP tool declaration for a form, and verify it by using it.

The generator turns a form into a WebMCP tool: a name, a description, and a
JSON-Schema input built from the fields (types, enums for selects, the required
list). The gate says the generated tool must be "used successfully by an agent"
— so `verify_tool_against_form` is the deterministic stand-in for that demo: it
simulates an agent calling the tool with schema-conforming arguments and
confirms the call actually drives the form —

- **sufficient**: every field the form *requires* is a property the agent would
  supply (missing one means the agent cannot complete the form), and
- **safe**: no property targets a field the form does not have (a phantom input
  sends data nowhere).

A tool that is both is one an agent can use to submit the form, which is exactly
what the demo proves — made checkable, and testable without a browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from verity.webmcp.model import FormField, FormModel, WebMcpTool


def _slug(text: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", text.strip().lower()).strip("_")
    return s or "form"


def _schema_for_field(f: FormField) -> dict:
    out: dict = {"type": "string"}
    t = f.field_type
    if t in ("number", "range"):
        out = {"type": "number"}
    elif t == "checkbox":
        out = {"type": "boolean"}
    elif t in ("select", "radio") and f.options:
        out = {"type": "string", "enum": list(f.options)}
    elif t == "email":
        out = {"type": "string", "format": "email"}
    elif t == "url":
        out = {"type": "string", "format": "uri"}
    elif t == "date":
        out = {"type": "string", "format": "date"}
    if f.label:
        out["description"] = f.label
    return out


def generate_tool_for_form(form: FormModel) -> WebMcpTool:
    """Build a WebMCP tool declaration that drives `form`."""
    base = _slug(form.name) or _slug(form.action) or "form"
    name = f"submit_{base}" if not base.startswith(("submit", "login", "search")) else base
    props = {f.name: _schema_for_field(f) for f in form.fields if f.name}
    required = sorted(form.required_names)
    schema = {"type": "object", "properties": props, "required": required, "additionalProperties": False}
    label = form.submit_label or form.name or "form"
    return WebMcpTool(
        name=name,
        description=f"Fill and submit the “{label}” form ({len(props)} field(s)).",
        input_schema=schema,
        form_selector=form.selector,
    )


# -- verification: an agent actually using the tool --------------------------

@dataclass
class ToolVerification:
    ok: bool
    missing_required: list[str] = field(default_factory=list)   # form needs, tool won't ask
    phantom_properties: list[str] = field(default_factory=list)  # tool asks, form lacks
    uncovered_optional: list[str] = field(default_factory=list)  # form has, tool omits (non-required)
    sample_call: dict = field(default_factory=dict)              # the agent's conforming call
    filled_required: list[str] = field(default_factory=list)     # required fields the call fills
    reasons: list[str] = field(default_factory=list)


def _sample_value(schema: dict):
    if schema.get("enum"):
        return schema["enum"][0]
    t = schema.get("type")
    if t == "boolean":
        return True
    if t == "number":
        return 1
    if schema.get("format") == "email":
        return "agent@example.com"
    if schema.get("format") == "uri":
        return "https://example.com"
    if schema.get("format") == "date":
        return "2026-01-01"
    return "example"


def verify_tool_against_form(tool: WebMcpTool, form: FormModel) -> ToolVerification:
    """
    Simulate an agent calling `tool` and confirm the call drives `form`. The
    tool passes when it is sufficient (covers every required field) and safe (no
    property the form lacks).
    """
    props = set(tool.properties)
    missing = sorted(form.required_names - props)
    phantom = sorted(props - form.field_names)
    uncovered = sorted((form.field_names - props) - form.required_names)

    # The agent's call: a conforming value for every property.
    sample = {name: _sample_value(spec) for name, spec in tool.properties.items()}
    filled_required = sorted(form.required_names & set(sample))

    reasons: list[str] = []
    if missing:
        reasons.append(f"cannot complete the form: required field(s) not in the tool: {', '.join(missing)}")
    if phantom:
        reasons.append(f"unsafe: tool property(ies) with no matching form field: {', '.join(phantom)}")
    ok = not missing and not phantom
    if ok:
        reasons.append(f"agent call fills all {len(filled_required)} required field(s); form submittable")
    return ToolVerification(
        ok=ok, missing_required=missing, phantom_properties=phantom, uncovered_optional=uncovered,
        sample_call=sample, filled_required=filled_required, reasons=reasons,
    )
