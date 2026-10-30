# Nikhil — Week 16 Track A is in (WebMCP readiness + generator, M3)

**From Rohan.** Built and unit-tested without a browser (static HTML extraction),
no network, no spend. This is the WebMCP half of the M3 gate; your ACR/VPAT
(B16.1–B16.3) is the other half.

## What landed

| # | What | Where |
|---|---|---|
| A16.1′ | **WebMCP readiness checks** — registered tools, form coverage, schema validity; an honest score | `verity/webmcp/readiness.py` |
| A16.2′ | **Declaration generator** — form → WebMCP tool, *verified by simulating an agent calling it* | `verity/webmcp/generator.py` |
| — | HTML extraction (forms + declared tools) and the `verity webmcp` CLI | `verity/webmcp/extract.py`, `verity/webmcp/model.py`, CLI |

## The gate, made checkable

The M3 gate says "a generated WebMCP tool is used successfully by an agent in a
demo." `verify_tool_against_form` is the deterministic stand-in for that demo:
it simulates an agent calling the generated tool with schema-conforming
arguments and confirms the call drives the form —

- **sufficient**: every *required* form field is a property the agent would
  supply (else it can't complete the form), and
- **safe**: no property targets a field the form lacks (a phantom input).

A tool that is both is one an agent can submit the form with. The CLI
(`verity webmcp <page> --generate`) prints each generated declaration with
`verified: agent can submit the form` or the exact reason it isn't — which is
the demo, reproducible in CI.

## The WebMCP declaration convention Verity reads

`<script type="application/webmcp+json">{"tools":[{name, description,
inputSchema, form}]}</script>` (and `input_schema`/`form_selector` aliases). If
your ACR wants to cite agent-readiness, `check_readiness(page).score` is the
number; `ready` is the boolean. Extraction is static HTML today (server-rendered
forms, the common case); a rendered-DOM supplement via the node worker is the
obvious next step if you need client-rendered forms.

## For the ACR (B16.x)

Two fields map straight into an agent-readiness row:

```python
from verity.webmcp import extract_page_from_html, check_readiness
report = check_readiness(extract_page_from_html(html, url))
report.score        # 0-100, coverage-driven, penalised by invalid schemas
report.uncovered    # form selectors an agent cannot drive
report.issues       # [(code, level, message, selector)]
```

Keep the honesty rule you own for the ACR: an **untested** agent-readiness claim
is never "Supports". A form with no tool is `uncovered` (a warning), not a
silent pass; a page with no forms scores 100 with an *info* note, not a false
"fully ready".

## Question

The readiness score weights coverage; invalid schemas subtract 15 each. If your
ACR scoring wants a different weighting (e.g. validity as a hard gate), it's one
function (`readiness._score`) — tell me the rule and I'll match the ACR.
