"""
Week 16 Track A — WebMCP readiness and the declaration generator.

Proves: forms and declared tools extract from HTML; the readiness checks score a
page honestly (no tools over real forms is not ready; a page with no forms is
not marked down); the generator builds a correct schema from a form; and the
"agent uses the tool" verification catches an insufficient tool (misses a
required field) and an unsafe one (a phantom property), and passes a tool that
covers the form.
"""

from verity.webmcp import (
    check_readiness,
    extract_forms_from_html,
    extract_page_from_html,
    extract_tools_from_html,
    generate_tool_for_form,
    verify_tool_against_form,
)
from verity.webmcp.model import FormField, FormModel, WebMcpPage, WebMcpTool


_LOGIN = """
<form id="login" action="/login" method="post">
  <label for="email">Email</label><input id="email" name="email" type="email" required>
  <label for="pw">Password</label><input id="pw" name="password" type="password" required>
  <label for="remember">Remember me</label><input id="remember" name="remember" type="checkbox">
  <button type="submit">Sign in</button>
</form>
"""


# --- extraction ------------------------------------------------------------

def test_extract_form_fields_types_labels_required():
    forms = extract_forms_from_html(_LOGIN)
    assert len(forms) == 1
    f = forms[0]
    assert f.selector == "#login" and f.method == "post" and f.submit_label == "Sign in"
    by = {x.name: x for x in f.fields}
    assert by["email"].field_type == "email" and by["email"].required and by["email"].label == "Email"
    assert by["password"].required and by["remember"].field_type == "checkbox" and not by["remember"].required
    assert f.required_names == {"email", "password"}


def test_extract_ignores_submit_and_hidden_inputs():
    html = '<form><input type="hidden" name="csrf"><input name="q"><input type="submit"></form>'
    f = extract_forms_from_html(html)[0]
    assert f.field_names == {"q"}  # hidden + submit excluded


def test_extract_declared_tools():
    html = ('<script type="application/webmcp+json">'
            '{"tools":[{"name":"do_search","description":"Search","inputSchema":'
            '{"type":"object","properties":{"q":{"type":"string"}},"required":["q"]},"form":"#s"}]}'
            '</script>')
    tools = extract_tools_from_html(html)
    assert len(tools) == 1 and tools[0].name == "do_search" and tools[0].form_selector == "#s"
    assert tools[0].required == {"q"}


# --- readiness -------------------------------------------------------------

def test_no_tools_over_real_forms_is_not_ready():
    page = extract_page_from_html(_LOGIN, "http://x")
    report = check_readiness(page)
    assert report.tool_count == 0 and report.form_count == 1
    assert report.uncovered == ["#login"] and report.score == 0
    assert any(i.code == "no-webmcp-tools" and i.level == "error" for i in report.issues)


def test_page_with_no_forms_is_ready_not_penalised():
    report = check_readiness(WebMcpPage(url="http://x", tools=[], forms=[]))
    assert report.score == 100 and report.ready
    assert any(i.code == "no-webmcp-tools" and i.level == "info" for i in report.issues)


def test_covered_form_scores_full():
    page = extract_page_from_html(_LOGIN, "http://x")
    # A tool generated from the form covers it.
    page.tools = [generate_tool_for_form(page.forms[0])]
    report = check_readiness(page)
    assert report.covered == ["#login"] and report.uncovered == [] and report.score == 100


def test_invalid_schema_is_flagged_and_penalised():
    page = extract_page_from_html(_LOGIN, "http://x")
    page.tools = [WebMcpTool(name="bad", description="", input_schema={"type": "array"},
                             form_selector="#login")]
    report = check_readiness(page)
    assert "bad" in report.invalid_schemas
    assert any(i.code == "invalid-schema" for i in report.issues)
    assert report.uncovered == ["#login"]  # an invalid tool cannot cover the form


# --- generator + verification ----------------------------------------------

def test_generate_tool_builds_schema_from_fields():
    tool = generate_tool_for_form(extract_forms_from_html(_LOGIN)[0])
    assert tool.form_selector == "#login"
    props = tool.properties
    assert props["email"] == {"type": "string", "format": "email", "description": "Email"}
    assert props["remember"]["type"] == "boolean"
    assert set(tool.required) == {"email", "password"}


def test_generated_tool_verifies_against_its_form():
    form = extract_forms_from_html(_LOGIN)[0]
    v = verify_tool_against_form(generate_tool_for_form(form), form)
    assert v.ok and set(v.filled_required) == {"email", "password"}
    assert v.sample_call["email"] == "agent@example.com" and v.sample_call["remember"] is True


def test_verify_catches_insufficient_tool():
    form = extract_forms_from_html(_LOGIN)[0]
    # A tool that omits the required password field.
    tool = WebMcpTool(name="t", description="",
                      input_schema={"type": "object", "properties": {"email": {"type": "string"}},
                                    "required": ["email"]})
    v = verify_tool_against_form(tool, form)
    assert not v.ok and "password" in v.missing_required


def test_verify_catches_unsafe_phantom_property():
    form = extract_forms_from_html(_LOGIN)[0]
    tool = WebMcpTool(name="t", description="", input_schema={
        "type": "object",
        "properties": {"email": {"type": "string"}, "password": {"type": "string"},
                       "admin": {"type": "boolean"}},
        "required": ["email", "password"]})
    v = verify_tool_against_form(tool, form)
    assert not v.ok and "admin" in v.phantom_properties


def test_enum_from_select_options():
    form = FormModel(selector="#f", fields=[
        FormField(name="size", field_type="select", required=True, options=("s", "m", "l"))])
    tool = generate_tool_for_form(form)
    assert tool.properties["size"] == {"type": "string", "enum": ["s", "m", "l"]}
    assert verify_tool_against_form(tool, form).sample_call["size"] == "s"
