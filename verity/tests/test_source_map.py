"""
A15.2′ — selector → source location.

Proves plain-HTML mapping reports the right file and line for the common
selector shapes Verity emits, that a React dev build's `data-source` wins over
the built HTML, and that the Base64-VLQ source-map decoder resolves a generated
position back to its original source.
"""

from verity.remediation.source_map import (
    locate_selector,
    parse_selector,
    resolve_source_map_position,
)
from verity.remediation.source_map import _vlq_decode


# --- selector parsing ------------------------------------------------------

def test_parse_selector_shapes():
    s = parse_selector('button#go.primary[data-vbid="3"]')
    assert s.tag == "button" and s.id == "go" and "primary" in s.classes
    assert ("data-vbid", "3") in s.attrs


def test_parse_selector_takes_the_target_of_a_descendant_chain():
    s = parse_selector("form .row input#email")
    assert s.tag == "input" and s.id == "email"


# --- plain HTML ------------------------------------------------------------

def test_locate_selector_reports_file_and_line(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(
        "<!doctype html>\n"
        "<html><body>\n"
        '  <button id="go">Go</button>\n'
        '  <input id="email" type="email">\n'
        "</body></html>\n",
        encoding="utf-8",
    )
    loc = locate_selector("#email", tmp_path)
    assert loc is not None and loc.file.endswith("page.html")
    assert loc.line == 4 and loc.source == "html"
    assert "email" in loc.snippet


def test_locate_selector_matches_by_attribute(tmp_path):
    (tmp_path / "p.html").write_text('<a href="/x" data-vbid="7">Link</a>', encoding="utf-8")
    loc = locate_selector('[data-vbid="7"]', tmp_path)
    assert loc is not None and loc.line == 1


def test_locate_selector_missing_returns_none(tmp_path):
    (tmp_path / "p.html").write_text("<p>nothing here</p>", encoding="utf-8")
    assert locate_selector("#absent", tmp_path) is None


def test_react_data_source_wins_over_built_html(tmp_path):
    (tmp_path / "built.html").write_text(
        '<button id="go" data-source="src/App.jsx:42:6">Go</button>', encoding="utf-8")
    loc = locate_selector("#go", tmp_path)
    assert loc.source == "react-dev" and loc.file == "src/App.jsx" and loc.line == 42 and loc.column == 6


# --- source maps -----------------------------------------------------------

def test_vlq_decode_basics():
    assert _vlq_decode("A") == [0]
    assert _vlq_decode("AAAA") == [0, 0, 0, 0]
    assert _vlq_decode("C") == [1]
    assert _vlq_decode("D") == [-1]


def test_resolve_source_map_position():
    # One mapping on generated line 1, col 0 -> source 0, line 0, col 0.
    smap = {"version": 3, "sources": ["src/app.ts"], "names": [], "mappings": "AAAA"}
    loc = resolve_source_map_position(smap, line=1, column=0)
    assert loc is not None and loc.file == "src/app.ts"
    assert loc.line == 1 and loc.source == "source-map"


def test_resolve_source_map_out_of_range_returns_none():
    smap = {"sources": ["a.ts"], "mappings": "AAAA"}
    assert resolve_source_map_position(smap, line=5, column=0) is None
