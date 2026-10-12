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

## Status

**End of Phase 1 (10 Aug – 20 Sep 2026).** A scan runs end to end today: it
renders a real page in Chromium, runs `axe-core`, adjudicates the results
axe declines to judge, and exits non-zero when an authoritative failure
exists.

Verified against paired fixtures: the page with a deliberate contrast
violation yields exactly one authoritative SC 1.4.3 finding on the right
element and exits 1; the clean page yields none and exits 0. See
[`node-worker/test/render-axe.test.mjs`](node-worker/test/render-axe.test.mjs).

### What works

| Capability | State |
|---|---|
| Render + `axe-core`, all four result buckets | Working |
| WCAG criterion mapping, `best-practice` rules excluded | Working |
| **Contrast-over-image adjudication** — `incomplete` resolved from real sampled pixels | Working |
| Element capture with boxes in CSS *and* device pixels | Working |
| Deduplication and waivers | Working |
| Per-scan latency in the report | Working |
| Build gating on authoritative findings only | Working |

The contrast wedge is the thing worth knowing about. Where `axe-core`
returns `incomplete` — most often text over a background image, which it
cannot read — Verity samples the actual rendered pixels and applies WCAG
arithmetic to produce an **authoritative** verdict. No model is involved in
that path.

It only decides where the answer is unambiguous. SC 1.4.3 requires 4.5:1 for
normal text but 3:1 for large text, and the rendered font size is not
currently available, so a ratio between 3.0 and 4.5 is reported as
`cantTell` rather than guessed. That is deliberate: a wrong finding is worse
than a missing one.

### What does not work yet

- **Keyboard traversal** — the Python judgments (SC 2.1.1 / 2.1.2 / 2.4.3 /
  2.4.7) are written and tested, but the browser-side traversal is not built,
  so nothing calls them
- **Vision** — descoped to an experiment after Spike A. An 8B model abstained
  on 79% of cases and produced zero false positives but almost no findings.
  Recorded honestly in
  [`docs/adr/0002-vision-descope-decision.md`](docs/adr/0002-vision-descope-decision.md)
- **Audio agent, calibration, SARIF/VPAT reports, the GitHub Action** — not
  started (Phases 2–4)

For the full picture — including what is half-built and why — see
[`docs/status.md`](docs/status.md). The schedule is in
[`docs/execution-plan.md`](docs/execution-plan.md); each directory's own
`README.md` carries its current state.

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
uv run pytest verity/tests/
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
