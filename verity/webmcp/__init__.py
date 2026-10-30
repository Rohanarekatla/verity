"""
Week 16 Track A — WebMCP: is this page usable by an agent through declared tools?

WebMCP lets a page publish machine-callable tools (name, description, JSON-Schema
input, bound to a form or handler) so an agent acts structurally instead of
scraping the DOM. Verity's job here is two-sided:

- **A16.1′ readiness** — are tools declared, do they cover the page's forms, are
  their schemas valid? A readiness report with an honest score.
- **A16.2′ generator** — for a form with no tool, generate a correct WebMCP tool
  declaration, and *verify* it the way the gate demands: by simulating an agent
  actually calling it and confirming the call drives the form (every required
  field supplied, no phantom input).
"""

from verity.webmcp.extract import (
    extract_forms_from_html,
    extract_page_from_html,
    extract_tools_from_html,
)
from verity.webmcp.generator import (
    ToolVerification,
    generate_tool_for_form,
    verify_tool_against_form,
)
from verity.webmcp.model import FormField, FormModel, WebMcpPage, WebMcpTool
from verity.webmcp.readiness import ReadinessIssue, ReadinessReport, check_readiness

__all__ = [
    "FormField", "FormModel", "WebMcpPage", "WebMcpTool",
    "extract_forms_from_html", "extract_tools_from_html", "extract_page_from_html",
    "check_readiness", "ReadinessReport", "ReadinessIssue",
    "generate_tool_for_form", "verify_tool_against_form", "ToolVerification",
]
