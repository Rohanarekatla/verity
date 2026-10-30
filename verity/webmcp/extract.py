"""
Week 16 Track A — extract WebMCP tools and forms from a page's HTML.

Static HTML extraction, so it is pure and tested without a browser: forms and
their fields come from the markup; declared tools come from a
`<script type="application/webmcp+json">` block holding `{"tools": [...]}` — the
declaration convention Verity reads. A dynamic page can supplement this with a
rendered DOM (the node worker), but the static pass is the testable core and
covers server-rendered forms, which is where accessibility+agent coverage
matters most.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from verity.webmcp.model import FormField, FormModel, WebMcpPage, WebMcpTool

_FIELD_TAGS = ("input", "select", "textarea")
_NON_DATA_TYPES = {"submit", "button", "reset", "image", "hidden"}


def _form_selector(form, index: int) -> str:
    if form.get("id"):
        return f"#{form['id']}"
    if form.get("name"):
        return f"form[name=\"{form['name']}\"]"
    return f"form:nth-of-type({index + 1})"


def _label_for(el, soup) -> str:
    fid = el.get("id")
    if fid:
        lab = soup.find("label", attrs={"for": fid})
        if lab:
            return lab.get_text(" ", strip=True)
    parent_label = el.find_parent("label")
    if parent_label:
        return parent_label.get_text(" ", strip=True)
    return el.get("aria-label", "") or el.get("placeholder", "")


def _field(el, soup) -> FormField | None:
    tag = el.name
    if tag == "input":
        ftype = (el.get("type") or "text").lower()
        if ftype in _NON_DATA_TYPES:
            return None
    elif tag == "select":
        ftype = "select"
    else:
        ftype = "textarea"
    name = el.get("name") or el.get("id") or ""
    if not name:
        return None
    options: list[str] = []
    if tag == "select":
        options = [o.get("value", o.get_text(strip=True)) for o in el.find_all("option")
                   if o.get("value") or o.get_text(strip=True)]
    return FormField(
        name=name, field_type=ftype, label=_label_for(el, soup),
        required=el.has_attr("required") or el.get("aria-required") == "true",
        options=tuple(options),
    )


def extract_forms_from_html(html: str) -> list[FormModel]:
    """Every form in the HTML, with its data-bearing fields."""
    soup = BeautifulSoup(html, "html.parser")
    forms: list[FormModel] = []
    for i, form in enumerate(soup.find_all("form")):
        fields = [f for f in (_field(el, soup) for el in form.find_all(_FIELD_TAGS)) if f]
        submit = form.find(attrs={"type": "submit"}) or form.find("button")
        forms.append(FormModel(
            selector=_form_selector(form, i),
            name=form.get("name") or form.get("id") or "",
            action=form.get("action", ""), method=(form.get("method") or "get").lower(),
            fields=fields,
            submit_label=(submit.get("value") or submit.get_text(" ", strip=True)) if submit else "",
        ))
    return forms


def extract_tools_from_html(html: str) -> list[WebMcpTool]:
    """Declared WebMCP tools from a `<script type="application/webmcp+json">`."""
    soup = BeautifulSoup(html, "html.parser")
    tools: list[WebMcpTool] = []
    for script in soup.find_all("script", attrs={"type": "application/webmcp+json"}):
        try:
            data = json.loads(script.string or "{}")
        except (ValueError, TypeError):
            continue
        for t in data.get("tools", []) if isinstance(data, dict) else []:
            if not isinstance(t, dict) or "name" not in t:
                continue
            tools.append(WebMcpTool(
                name=t["name"], description=t.get("description", ""),
                input_schema=t.get("inputSchema") or t.get("input_schema") or {},
                form_selector=t.get("form") or t.get("form_selector"),
            ))
    return tools


def extract_page_from_html(html: str, url: str = "") -> WebMcpPage:
    return WebMcpPage(url=url, tools=extract_tools_from_html(html), forms=extract_forms_from_html(html))
