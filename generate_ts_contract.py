"""
generate_ts_contract.py — A6.3

Generates the TypeScript mirror of the cross-language contract from
`verity-schema.json` (which `export_schema.py` produces from the Pydantic
models). The worker's hand-written interfaces — `RegionSample` in
`sampling.ts`, `TraversalResult` in `traverse.ts` — are what Track A builds to,
and they drifted from the Python once already (`element_screenshots`, Week 2),
caught only by reading the TypeScript by hand. A generated mirror plus a CI
drift check (see `test_contract_drift.py`) means that can't happen silently
again: change a boundary model, and if you don't regenerate, CI goes red.

This is deliberately a small, purpose-built generator rather than a dependency.
Our schema uses a known, limited subset of JSON Schema (objects, string enums,
$ref, arrays, anyOf-with-null for Optional, and bare dict), so a focused
emitter is both dependency-free — in keeping with the rest of the repo — and
easy to read when it needs changing.

    uv run python generate_ts_contract.py        # regenerate the .ts mirror

The output is checked in and must be regenerated whenever the schema changes;
the drift test fails if the committed file is stale.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "verity-schema.json"
TS_PATH = HERE / "node-worker" / "contract" / "contract-types.ts"

_HEADER = """\
/**
 * contract-types.ts — GENERATED, DO NOT EDIT BY HAND.
 *
 * The TypeScript mirror of the Python/Node contract, generated from
 * verity-schema.json by `uv run python generate_ts_contract.py` (A6.3).
 * Edit the Pydantic models in verity/models/schemas.py, run export_schema.py,
 * then regenerate this. CI fails if this file is out of date — see
 * verity/tests/test_contract_drift.py.
 *
 * These are the shapes that cross the RPC boundary. A worker handler that
 * returns one of these can import the type here instead of re-declaring it,
 * so the two sides cannot drift without a red build.
 */
"""


def _ts_type(node: dict) -> str:
    """Render one JSON-Schema node as a TypeScript type expression."""
    # A reference to another named definition.
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]

    # Optional / nullable and unions: anyOf. Collapse `{type: null}` into a
    # `| null` so `Optional[X]` becomes `X | null` rather than a noisy union.
    if "anyOf" in node:
        parts: list[str] = []
        has_null = False
        for sub in node["anyOf"]:
            if sub.get("type") == "null":
                has_null = True
            else:
                parts.append(_ts_type(sub))
        if has_null:
            parts.append("null")
        # de-dup while preserving order
        seen: set[str] = set()
        uniq = [p for p in parts if not (p in seen or seen.add(p))]
        return " | ".join(uniq) if uniq else "null"

    # A string enum -> a union of string literals.
    if "enum" in node:
        return " | ".join(json.dumps(v) for v in node["enum"])

    t = node.get("type")
    if t == "array":
        inner = _ts_type(node.get("items", {})) or "unknown"
        # Parenthesise a union element type so `(A | B)[]` is unambiguous.
        if "|" in inner:
            inner = f"({inner})"
        return f"{inner}[]"
    if t == "object" or (t is None and "properties" not in node and "enum" not in node and "$ref" not in node and "anyOf" not in node):
        # A bare dict (Pydantic `dict`) or an untyped node -> open record.
        return "Record<string, unknown>"
    if t == "integer" or t == "number":
        return "number"
    if t == "string":
        return "string"
    if t == "boolean":
        return "boolean"

    return "unknown"


def _render_interface(name: str, defn: dict) -> str:
    required = set(defn.get("required", []))
    lines = [f"export interface {name} {{"]
    for field, prop in defn.get("properties", {}).items():
        ts = _ts_type(prop)
        optional = field not in required
        # An optional field that is also explicitly nullable keeps the `| null`
        # — `?` means "may be absent", null means "present and null"; they are
        # different on the wire and must stay distinct (the focus_visible rule).
        lines.append(f"  {field}{'?' if optional else ''}: {ts};")
    lines.append("}")
    return "\n".join(lines)


def _render_enum(name: str, defn: dict) -> str:
    union = " | ".join(json.dumps(v) for v in defn["enum"])
    return f"export type {name} = {union};"


def render_ts(schema: dict) -> str:
    """Render the whole contract as a TypeScript source string."""
    defs = schema.get("$defs", {})
    blocks: list[str] = [_HEADER]
    for name in sorted(defs):
        defn = defs[name]
        if "enum" in defn and defn.get("type") == "string":
            blocks.append(_render_enum(name, defn))
        else:
            blocks.append(_render_interface(name, defn))
    return "\n\n".join(blocks) + "\n"


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    TS_PATH.write_text(render_ts(schema), encoding="utf-8")
    print(f"TypeScript contract mirror written to {TS_PATH}")
    print(f"{len(schema.get('$defs', {}))} definitions")


if __name__ == "__main__":
    main()
