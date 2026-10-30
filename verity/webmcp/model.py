"""
Week 16 Track A — the WebMCP data model.

The small set of types the readiness checks and the generator share: a form and
its fields (what the page has), and a WebMCP tool (what an agent can call). Kept
deliberately minimal and JSON-able — a tool's `input_schema` is a plain
JSON-Schema dict, because that is exactly what a page declares and an agent
reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class FormField:
    """One control in a form."""

    name: str
    field_type: str = "text"       # text|email|number|checkbox|radio|select|textarea|password|date|...
    label: str = ""
    required: bool = False
    options: tuple[str, ...] = ()  # for select / radio


@dataclass
class FormModel:
    """A form an agent would need to drive."""

    selector: str
    name: str = ""
    action: str = ""
    method: str = "get"
    fields: list[FormField] = field(default_factory=list)
    submit_label: str = ""

    @property
    def field_names(self) -> set[str]:
        return {f.name for f in self.fields if f.name}

    @property
    def required_names(self) -> set[str]:
        return {f.name for f in self.fields if f.required and f.name}


@dataclass
class WebMcpTool:
    """A declared (or generated) WebMCP tool."""

    name: str
    description: str
    input_schema: dict
    form_selector: Optional[str] = None   # the form this tool drives, if any

    @property
    def properties(self) -> dict:
        return (self.input_schema or {}).get("properties", {}) or {}

    @property
    def required(self) -> set[str]:
        return set((self.input_schema or {}).get("required", []) or [])


@dataclass
class WebMcpPage:
    """What Verity extracted from a page: the declared tools and the forms."""

    url: str = ""
    tools: list[WebMcpTool] = field(default_factory=list)
    forms: list[FormModel] = field(default_factory=list)
