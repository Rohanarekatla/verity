# Nikhil — Week 15, Track A is in (MCP server, source map, ACT runner)

**From Rohan.** Built and unit-tested without a browser, network, or spend. This
is the *verifier* half of verifier-gated remediation — your fix loop (B15.1′)
is the coding agent that calls these tools and accepts a patch only when they
say the defect is gone and no regression appeared.

## What landed

| # | What | Where |
|---|---|---|
| A15.1′ | **Verity MCP server** (stdio, JSON-RPC 2.0): tools `scan`, `explain_finding`, `sample_contrast`, `traverse`, `run_contract`, `virtual_sr_read`, `baseline_diff` | `verity/mcp/`, CLI `verity mcp` |
| A15.2′ | **Source mapping** selector → file:line — plain HTML (position-tracking parse), React dev `data-source`, and a Base64-VLQ source-map resolver | `verity/remediation/source_map.py` |
| A15.3 | **ACT runner** — maps Verity outcomes to ACT, aggregates per-rule pass rate honestly (cantTell is never a pass) | `eval/act_runner.py` |

## The tools your fix loop calls

Every tool is typed (JSON-Schema input) and small-output. Idempotency is
declared per tool: **only `scan` renders / does work**; the other six are pure
reads over a scan, safe to retry. The loop you want is:

1. `scan(url)` → findings.
2. `explain_finding(report, id)` → the fix *and* `confirm_with`: the exact tool
   that confirms this SC (`1.4.3` → `sample_contrast`, `2.1.1` → `traverse`,
   `4.1.2` → `run_contract`, `1.1.1` → `virtual_sr_read`). This is the single
   most useful field for an agent — it closes the loop.
3. edit the source (A15.2′ gives you the file:line from the finding's selector).
4. `baseline_diff(url, baseline)` → **accept only if `regression_free`** and the
   target finding is gone. This is the gate; it is the "no new finding" half of
   the W15 gate (≥60% fixed, **0 accepted regressions**).

Dispatch and the protocol are in `verity/mcp/{tools,server}.py`; the engine
wiring is `capabilities.default_capabilities()`. A bad call returns an MCP error
result (readable, correctable), never an exception over stdio.

## One integrity note on the engine wiring

`capabilities._DefaultCapabilities` runs **one `scan_url`** and reads the
check-specific answers out of the report the engine already computes (contrast,
keyboard, interaction, name findings) — so `sample_contrast`/`traverse`/
`run_contract`/`virtual_sr_read` are filtered reads of one scan, not four
renders. That part needs a browser + the node worker, so it is exercised by the
hand-done fix (the W15 artifact), not unit tests. The catalog, validation,
dispatch, protocol, `explain_finding`, and the confirm-tool mapping are all unit
tested. If you want a finer-grained `sample_contrast` (one element, not a
filtered scan) say so and I'll add a direct `sampleRegion` RPC path.

## Source map (A15.2′) — what you get

`locate_selector(selector, root)` → `SourceLocation(file, line, column, source,
snippet)`. Plain HTML today (the selector shapes Verity emits: tag/#id/.class/
[attr]/[data-vbid]); a React dev build's `data-source` wins when present;
`resolve_source_map_position(map, line, col)` handles bundled JS. The fix loop
feeds the finding's `evidence.dom_selector` straight in.

## ACT runner (A15.3) — the honesty you asked for

`run_act(cases, scan_fn)` → per-rule `pass_rate` **and** `decided_pass_rate`,
with `undecided` (cantTell) counted against the headline and excluded from the
decided rate. A cantTell is never scored as a pass. Point `scan_fn` at the MCP
`scan` tool (or `scan_url`) and feed a W3C ACT case manifest to
`load_cases(path)`; `format_report` writes the gate table.

## Questions

1. **Fix-loop interface.** Do you want to drive the tools in-process
   (`from verity.mcp import call_tool` + `default_capabilities()`) or over stdio
   (`verity mcp`)? In-process is simpler for B15.1′; stdio is what an external
   coding agent would use. Both work today.
2. **ACT corpus.** The runner takes a case manifest; do you want me to vendor a
   pinned slice of the W3C ACT test cases (with a fetch script), or will B15.2′'s
   fix-eval corpus double as the input?
