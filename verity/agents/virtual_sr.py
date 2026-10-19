"""
B9.2 — a virtual screen reader for CI (Track B, Week 9).

Headless Linux, no real screen reader anywhere. Every render already saves
Chromium's full accessibility tree (`ax-tree.json`, render.ts via CDP
`Accessibility.getFullAXTree`): the roles, the computed accessible names
(the browser's `computeAccessibleName`, shadow DOM included) and the states a
screen reader would read. This module walks that tree the way a screen reader
in browse mode walks a page and speaks each stop through B9.1's
`announce.predict` — so "what would a screen reader user hear?" becomes a
pure function of a JSON file, testable in CI and identical on every machine.

What it is NOT: NVDA, JAWS or VoiceOver. Their exact wording, verbosity
settings and quirks are out of scope (execution plan, deferred list: "Real
screen-reader automation in CI — fragile; virtual SR + accname is a better
engineering choice"). The transcript answers the questions a check needs —
is this control named, is its role exposed, is its state spoken — not "does
it sound like NVDA 2026.3".

Walk rules (browse mode):

- ignored nodes are skipped, but their children are still visited (an
  ignored wrapper `div` can hold rendered content);
- `StaticText` is spoken as text; `InlineTextBox`/`LineBreak` are layout;
- a control, heading or image is spoken once as a whole — name, role,
  states — and its descendants are NOT read again (that text is its name);
- a container a screen reader announces on entry (landmark, dialog, list,
  tab list, menu, list box, table…) is spoken, then its contents are walked.

Usage (for humans):

    uv run python -m verity.agents.virtual_sr .verity/cache/<hash>/ax-tree.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from verity.agents.announce import CONTROL_ROLES, Announcement, predict

# Spoken whole; their subtree is their name.
LEAF_ROLES = (CONTROL_ROLES - {"listbox"}) | {"heading", "img", "image"}

# Spoken on entry, then walked.
CONTAINER_ROLES = frozenset({
    "navigation", "main", "banner", "contentinfo", "complementary", "search",
    "region", "form", "dialog", "alertdialog", "list", "tablist", "tabpanel",
    "menu", "menubar", "listbox", "table", "grid", "tree", "alert", "status", "group",
})
# Announced only when named (an unnamed region/group is just a div to AT).
_NAMED_ONLY = frozenset({"region", "group", "form"})

_SILENT = frozenset({"InlineTextBox", "LineBreak"})

# CDP AXPropertyName -> the state keys announce.state_phrases understands.
_PROPERTY_STATES = {
    "expanded": "expanded",
    "selected": "selected",
    "checked": "checked",
    "pressed": "pressed",
    "disabled": "disabled",
    "required": "required",
    "invalid": "invalid",
    "level": "level",
    "hasPopup": "haspopup",
    "modal": "modal",
    "readonly": "readonly",
}


@dataclass
class AxNode:
    node_id: str
    role: Optional[str]
    name: Optional[str]
    ignored: bool
    child_ids: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def states(self) -> dict[str, Any]:
        return {key: self.properties[prop] for prop, key in _PROPERTY_STATES.items() if prop in self.properties}

    @property
    def focusable(self) -> bool:
        return self.properties.get("focusable") is True


@dataclass
class AxTree:
    nodes: dict[str, AxNode]
    root_id: Optional[str]


def _value(obj: Any) -> Any:
    return obj.get("value") if isinstance(obj, dict) else None


def parse_ax_tree(data: dict) -> AxTree:
    """Parse the CDP `Accessibility.getFullAXTree` payload ({"nodes": [...]})."""
    nodes: dict[str, AxNode] = {}
    order: list[str] = []
    for raw in data.get("nodes", []):
        node_id = str(raw.get("nodeId"))
        props = {p.get("name"): _value(p.get("value")) for p in raw.get("properties", []) if p.get("name")}
        name = _value(raw.get("name"))
        nodes[node_id] = AxNode(
            node_id=node_id,
            role=_value(raw.get("role")),
            name=name if isinstance(name, str) else None,
            ignored=bool(raw.get("ignored", False)),
            child_ids=[str(c) for c in raw.get("childIds", [])],
            parent_id=str(raw["parentId"]) if raw.get("parentId") is not None else None,
            properties=props,
        )
        order.append(node_id)
    root = next((i for i in order if nodes[i].parent_id is None), order[0] if order else None)
    return AxTree(nodes=nodes, root_id=root)


def load_ax_tree(source: Union[str, Path, dict]) -> AxTree:
    """Load a tree from an `ax-tree.json` path or an already-parsed payload."""
    if isinstance(source, dict):
        return parse_ax_tree(source)
    return parse_ax_tree(json.loads(Path(source).read_text(encoding="utf-8")))


def _walk(tree: AxTree):
    """Depth-first, document order, iterative (real pages nest deeper than Python's recursion limit)."""
    if tree.root_id is None:
        return
    stack = [tree.root_id]
    seen: set[str] = set()
    while stack:
        node_id = stack.pop()
        if node_id in seen or node_id not in tree.nodes:
            continue
        seen.add(node_id)
        node = tree.nodes[node_id]
        descend = yield node
        if descend is not False:
            stack.extend(reversed(node.child_ids))


def browse(tree: AxTree) -> list[Announcement]:
    """The browse-mode transcript: every stop a screen reader would read, in order."""
    out: list[Announcement] = []
    walker = _walk(tree)
    try:
        node = next(walker)
        while True:
            descend = True
            role = node.role
            if node.ignored or role in (None, "RootWebArea"):
                pass
            elif role in _SILENT:
                descend = False
            elif role == "StaticText":
                text = " ".join((node.name or "").split())
                if text:
                    out.append(Announcement(role=None, name=text, text=text, source=node.node_id))
                descend = False
            elif role in LEAF_ROLES:
                out.append(predict(role, node.name, node.states, source=node.node_id))
                descend = False
            elif role in CONTAINER_ROLES and (role not in _NAMED_ONLY or (node.name or "").strip()):
                out.append(predict(role, node.name, node.states, source=node.node_id))
            node = walker.send(descend)
    except StopIteration:
        pass
    return out


def focusables(tree: AxTree) -> list[Announcement]:
    """
    What a user hears landing on each focusable element, in tree order.

    The accessibility tree says *focusable*, not *in the Tab order* — a
    tabindex=-1 element is focusable too, and positive tabindex reorders Tab.
    The real Tab order is the traversal's job (keyboard.py); this is the
    announcement half.
    """
    return [
        predict(n.role, n.name, n.states, source=n.node_id)
        for n in _iter_all(tree)
        if not n.ignored and n.focusable and n.role not in (None, "RootWebArea")
    ]


def _iter_all(tree: AxTree):
    walker = _walk(tree)
    try:
        node = next(walker)
        while True:
            yield node
            node = walker.send(True)
    except StopIteration:
        return


def unnamed_controls(tree: AxTree) -> list[Announcement]:
    """Controls a screen reader user would hear only as their role ("button")."""
    return [a for a in browse(tree) if a.unnamed_control]


def transcript(tree: AxTree) -> str:
    return "\n".join(a.text for a in browse(tree))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m verity.agents.virtual_sr <ax-tree.json>", file=sys.stderr)
        return 2
    tree = load_ax_tree(argv[1])
    print(transcript(tree))
    unnamed = unnamed_controls(tree)
    if unnamed:
        print(f"\n{len(unnamed)} control(s) announced without a name:", file=sys.stderr)
        for a in unnamed:
            print(f"  ax node {a.source}: {a.text!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
