# Verity

Verity is a WCAG accessibility conformance engine. It screens a page
with `axe-core`, adjudicates ambiguous results deterministically (e.g.
contrast over images), and — where a model is used at all — treats the
model as a *localiser* whose output still has to clear a deterministic
check before it becomes a finding.

It's a **polyglot system**: a Python orchestrator (ML, calibration,
trust machinery, report generation) drives a long-lived Node.js worker
(Playwright + `axe-core`) over JSON-RPC 2.0 on stdio. Neither language
does the other's job — Python doesn't have a trustworthy `axe-core`
equivalent, and Node doesn't have the ML ecosystem. See
[`docs/adr/0001-polyglot-json-rpc-over-stdio.md`](docs/adr/0001-polyglot-json-rpc-over-stdio.md)
for the full rationale.

## The story in one line

**The accessibility engine that refuses to lie.** Every finding carries its
provenance (authoritative / AI-assisted / needs review); nothing is ever
reported as passing that was not checked; and every scan says exactly what it
did *not* check.

## Install

```bash
git clone https://github.com/Rohanarekatla/verity && cd verity
cd node-worker && npm ci && npx playwright install chromium && npm run build && cd ..
uv sync
```

Requirements: Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 22.
Run every command from the repository root.

## Use it

```bash
# Scan a page (URL or local file). Exit 0 = no gating failures, 1 = gating failures, 2 = no verdict.
uv run python -m verity.cli scan https://example.com
uv run python -m verity.cli scan ./dist/index.html --sarif verity.sarif --earl report.jsonld --trace verity-trace.json

# Gate CI only on NEW findings
uv run python -m verity.cli scan ./dist/index.html --write-baseline .verity/baseline.json   # once
uv run python -m verity.cli scan ./dist/index.html --baseline .verity/baseline.json

# Can an AI agent complete a task on your site? (any provider; local Ollama works)
uv run python -m verity.cli agent-check https://example.com --task "Find the pricing page" --model ollama:qwen3:8b --confirm

# How ready is a page for AI agents, with evidence per point
uv run python -m verity.cli readiness https://example.com

# An Accessibility Conformance Report (VPAT 2.5, WCAG 2.2) from saved scans
uv run python -m verity.cli scan https://example.com -o scan.json
uv run python -m verity.cli acr scan.json --product "Example" --out acr.md --html acr.html

# Verity's checks as MCP tools for a coding agent; WebMCP readiness for forms
uv run python -m verity.cli mcp
uv run python -m verity.cli webmcp https://example.com --generate
```

In GitHub Actions use [`action/`](action/) — findings appear as inline PR
annotations on the built HTML they came from.

## What it checks

| Wedge | How | Verdict |
|---|---|---|
| axe-core, WCAG-tagged rules only | unmodified axe-core 4.13 | authoritative where axe is certain; its `incomplete` items are adjudicated or left for review |
| **Contrast over images and gradients** (1.4.3) | worst-case ratio from real rendered pixels, font size from the page | authoritative; `cantTell` when the pixels are not stable |
| **Keyboard** (2.1.1, 2.1.2, 2.4.3, 2.4.7) | real tab-order traversal, multi-cycle trap detection, focus ring by style + pixel diff | three-state: pass / fail / indeterminate (ADR-0004) |
| **APG widgets** — tabs, disclosure, menu button, dialog, combobox | keys actually pressed against hand-written contracts | WCAG failures gate; APG style deviations are reviewed only |
| **Agents** — `agent-check`, readiness, MCP, WebMCP | a real LLM agent through the accessibility tree; failures confirmed deterministically | an unconfirmed agent failure is never a site defect |

On the BC-C2 benchmark (`docs/measurements/benchmark-2026-10-19.md`) Verity
decided 202/202 contrast-over-image failures with 0 false; axe and Pa11y sent
all 202 to review and Lighthouse missed them silently. On keyboard/widget
defects Verity caught 7/7, every other tool 0/7.

## What it does not do

23 of the 55 WCAG 2.2 Level A/AA criteria have an automated check here; the
other 32 need a person, and Verity says so in every report. Full, honest list:
[`docs/limitations.md`](docs/limitations.md). Vision is an experiment behind a
flag (ADR-0002). Licences: [`docs/licenses.md`](docs/licenses.md).

## Status

All twenty weeks of the plan are built and tested (`uv run pytest` — 800+
tests). The Agent Accessibility Benchmark is pre-registered
(`docs/agentbench/preregistration.md`) and its runs are pending the pilot.
Schedule and decisions: [`docs/execution-plan.md`](docs/execution-plan.md),
[`docs/adr/`](docs/adr/).

## Layout

```
.
├── node-worker/          # TypeScript: browser + deterministic engines
│   ├── rpc/               # JSON-RPC 2.0 over stdio: protocol, framing, dispatch, handlers
│   ├── crawler/            # Chromium lifecycle, render → RenderArtifact, page handoff
│   ├── static/             # axe-core, accname, geometry, contrast math (authoritative)
│   ├── interaction/         # Keyboard vs APG contracts (Week 4)
│   └── state_explorer/       # Bounded modal/menu/error states (Week 17)
├── verity/                # Python: orchestration, models, ML agents, calibration, reports
│   ├── models/            # Pydantic schemas — source of truth for types on both sides
│   ├── orchestrator/       # Spawns/drives the Node worker; the scan pipeline
│   ├── agents/             # ML workers: vision, audio, contrast-over-image, validator
│   ├── calibration/        # Confidence calibration (isotonic, conformal)
│   ├── report/             # SARIF / VPAT-ACR / JUnit generators
│   └── tests/
├── eval/                  # Fault-injection harness + frozen accuracy baselines
├── data/                  # WCAG criteria, APG interaction contracts, test fixtures
├── rulepacks/              # Custom rule packs + their required fixtures
├── action/                 # GitHub Action wrapper (depends on verity/report/)
└── docs/adr/                # Architecture Decision Records
```

Every directory has its own `README.md` — read that before adding
files to it. For the Node side, [`node-worker/ARCHITECTURE.md`](node-worker/ARCHITECTURE.md) walks a
single request from stdin to stdout with diagrams and worked examples.

## How to work in this repo

Two people, two languages, one repo, organised by directory.

| Side | Directories | Test command |
|---|---|---|
| **Node** — browser, protocol, CI surface | `node-worker/` | `cd node-worker && npm test` |
| **Python** — orchestration, models, ML, eval | `verity/`, `eval/`, `data/`, `rulepacks/` | `uv run pytest verity/tests/` |

**Ownership rotates every phase** — neither engineer stays in one lane.
Current assignments and the rotation schedule are in
[`docs/team-plan.md`](docs/team-plan.md). A PR into a lane you don't
currently own gets reviewed by the person who does; that review is the
point.

You don't need the other side's toolchain installed to work on your
own — Node isn't required to touch `verity/`, and Python isn't
required to touch `node-worker/`. You only need both when testing the
full contract (see below).

**"Where do I put this?"**

- A new ML worker or verification step → `verity/agents/` (own file,
  read its `README.md` first — there's a rule about models never being
  the sole source of a verdict).
- A new WCAG/APG reference fact → `data/` (no code, just structured
  data).
- A new fault-injection type or accuracy check → `eval/`.
- A new output format (SARIF, JUnit, ...) → `verity/report/`.
- A change to what the worker can do (new RPC method, new field on a
  result) → **both** `node-worker/rpc/protocol.ts` and
  `verity/models/schemas.py` in the same PR. This is the one case
  that always touches both directories — see next section.

**Changing the shared contract**

`protocol.ts` and `schemas.py` are two views of the same interface.
If you change one without the other, the two processes silently start
disagreeing about what a message means. The rule:

1. Edit both files in the same PR.
2. Add/update a test on each side (`node-worker/test/`,
   `verity/tests/`) that exercises the change.
3. Run the contract check: `python3 node-worker/contract/reference_client.py`
   against a freshly built worker — it's the fastest way to see the
   two sides actually talking.
4. If the change reverses a decision in `docs/adr/`, update that ADR
   rather than leaving it to go stale.

**Before you propose a different design** for the transport, framing,
or error handling — check `docs/adr/` first. It usually already
records why the current approach was chosen and what alternative lost.

**CI** (`.github/workflows/ci.yml`) runs all three checks — Node
build+test, Python pytest, and the cross-language contract — on every
push and PR, so a break on either side is caught before merge.

## Getting started

### Node worker

```bash
cd node-worker
npm install
npx playwright install chromium
npm test
```

`npx playwright install` downloads the browser binary (once). `npm test`
builds, then runs the protocol suite and the render/axe gate tests —
19/19.

### Python orchestrator

```bash
cd ..
uv sync
uv run pytest
uv run python -m verity.cli scan https://example.com
```

The leading `cd ..` returns to the repo root after the Node block above.
The CLI runs as a module, so it must be launched from the root — from
`node-worker/` it fails with `No module named 'verity'`.

### Prove the cross-language contract

```bash
cd node-worker
npm run build
cd ..
python3 node-worker/contract/reference_client.py
```

## Contributing

[RUNNING.md](RUNNING.md) — install it and run a scan locally.
[CONTRIBUTING.md](CONTRIBUTING.md) — the shared RPC contract and PR
conventions.

## License

[MPL-2.0](LICENSE).
