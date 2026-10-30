"""
A15.2′ — selector → source location.

A finding names a DOM selector; a fix has to edit a *file*. This maps one to the
other. Plain HTML first, because it is the case every project has and the one
the fix loop starts on: scan the project's `.html` files, find the element the
selector matches, and report the file and 1-based line. Line numbers come from
a position-tracking parser (`html.parser.getpos`), because a fix needs to land
on a line, not just in a file.

Two further sources, for built apps:

- **React dev builds** carry the source location Babel injects
  (`data-source="file:line:col"` via `@babel/plugin-transform-react-jsx-source`,
  or the `__source` prop) — read it straight off the element when present.
- **JS source maps** map a bundled `(line, column)` back to the original file
  via the standard VLQ mappings; `resolve_source_map_position` does that lookup
  without a dependency.

Selector support is scoped to what Verity's findings actually emit —
`tag`, `#id`, `.class`, `[attr]`, `[attr="v"]`, `[data-vbid="n"]`, and a simple
`tag.class#id[attr]` combination — not arbitrary CSS, which would need a full
engine for no benefit here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional


@dataclass
class SourceLocation:
    file: str
    line: int
    column: int = 0
    source: str = "html"          # "html" | "react-dev" | "source-map"
    snippet: str = ""


# -- a tiny selector matcher -------------------------------------------------

@dataclass
class _Selector:
    tag: Optional[str]
    id: Optional[str]
    classes: tuple[str, ...]
    attrs: tuple[tuple[str, Optional[str]], ...]

    def matches(self, tag: str, attrs: dict) -> bool:
        if self.tag and self.tag != tag:
            return False
        if self.id and attrs.get("id") != self.id:
            return False
        have = set((attrs.get("class") or "").split())
        if any(c not in have for c in self.classes):
            return False
        for name, value in self.attrs:
            if name not in attrs:
                return False
            if value is not None and attrs[name] != value:
                return False
        return True


_SEL_TOKEN = re.compile(
    r'(?P<tag>^[a-zA-Z][\w-]*)'
    r'|#(?P<id>[\w-]+)'
    r'|\.(?P<cls>[\w-]+)'
    r'|\[(?P<attr>[\w:-]+)(?:(?:=|~=)"?(?P<val>[^\]"]*)"?)?\]'
)


def parse_selector(selector: str) -> _Selector:
    tag = id_ = None
    classes: list[str] = []
    attrs: list[tuple[str, Optional[str]]] = []
    # Only the last simple selector in a descendant chain is matched (the target).
    simple = selector.strip().split()[-1] if selector.strip() else ""
    for m in _SEL_TOKEN.finditer(simple):
        if m.group("tag"):
            tag = m.group("tag")
        elif m.group("id"):
            id_ = m.group("id")
        elif m.group("cls"):
            classes.append(m.group("cls"))
        elif m.group("attr"):
            attrs.append((m.group("attr"), m.group("val")))
    return _Selector(tag=tag, id=id_, classes=tuple(classes), attrs=tuple(attrs))


class _Locator(HTMLParser):
    """Records the first element matching the selector, with its line."""

    def __init__(self, selector: _Selector):
        super().__init__(convert_charrefs=True)
        self._sel = selector
        self.hit: Optional[tuple[int, int, dict]] = None

    def handle_starttag(self, tag, attrs):
        if self.hit is not None:
            return
        attr_map = {k: (v if v is not None else "") for k, v in attrs}
        if self._sel.matches(tag, attr_map):
            line, col = self.getpos()
            self.hit = (line, col, attr_map)


def locate_selector(selector: str, root: Path, *, extensions=(".html", ".htm")) -> Optional[SourceLocation]:
    """
    Find the source file and line of the element `selector` matches, scanning
    the HTML files under `root`. Returns the first match in sorted file order,
    or None. A React `data-source` on the matched element wins — it points at
    the real source, not the built HTML.
    """
    root = Path(root)
    files = [root] if root.is_file() else sorted(
        p for ext in extensions for p in root.rglob(f"*{ext}"))
    sel = parse_selector(selector)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        loc = _Locator(sel)
        loc.feed(text)
        if loc.hit is None:
            continue
        line, col, attrs = loc.hit
        react = _react_source(attrs)
        if react:
            return react
        snippet = text.splitlines()[line - 1].strip()[:200] if 0 < line <= len(text.splitlines()) else ""
        return SourceLocation(file=str(path), line=line, column=col, source="html", snippet=snippet)
    return None


_DATA_SOURCE = re.compile(r"^(?P<file>.+?):(?P<line>\d+)(?::(?P<col>\d+))?$")


def _react_source(attrs: dict) -> Optional[SourceLocation]:
    """A React dev build's `data-source="file:line:col"`, if present."""
    raw = attrs.get("data-source") or attrs.get("data-inspector-relative-path")
    if not raw:
        return None
    m = _DATA_SOURCE.match(raw.strip())
    if not m:
        return None
    return SourceLocation(file=m.group("file"), line=int(m.group("line")),
                          column=int(m.group("col") or 0), source="react-dev")


# -- JS source maps ----------------------------------------------------------

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_B64_INDEX = {c: i for i, c in enumerate(_B64)}


def _vlq_decode(segment: str) -> list[int]:
    """Decode a Base64-VLQ segment into signed integers (the source-map codec)."""
    values: list[int] = []
    shift = acc = 0
    for ch in segment:
        digit = _B64_INDEX[ch]
        acc += (digit & 0x1F) << shift
        if digit & 0x20:
            shift += 5
        else:
            value = acc >> 1
            values.append(-value if acc & 1 else value)
            shift = acc = 0
    return values


def resolve_source_map_position(source_map: dict, line: int, column: int) -> Optional[SourceLocation]:
    """
    Map a generated `(line, column)` (1-based line, 0-based column) back to its
    original source via a standard source map's `mappings`/`sources`. Returns
    the closest mapping at or before the position on that line, or None.
    """
    sources = source_map.get("sources") or []
    groups = (source_map.get("mappings") or "").split(";")
    if line - 1 >= len(groups):
        return None
    gen_col = src_i = src_line = src_col = 0
    best: Optional[tuple[int, int, int]] = None
    # Decode cumulatively up to and including the target line (fields are
    # relative across the whole file for source index/line/column).
    for li, group in enumerate(groups):
        gen_col = 0
        for seg in filter(None, group.split(",")):
            fields = _vlq_decode(seg)
            gen_col += fields[0]
            if len(fields) >= 4:
                src_i += fields[1]
                src_line += fields[2]
                src_col += fields[3]
            if li == line - 1 and gen_col <= column:
                best = (src_i, src_line, src_col)
    if best is None:
        return None
    si, sl, sc = best
    name = sources[si] if 0 <= si < len(sources) else "?"
    return SourceLocation(file=name, line=sl + 1, column=sc, source="source-map")
