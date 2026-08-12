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

Early — Week 1 in progress. Working end to end today:

- `render` navigates a real page with Playwright and captures a
  `RenderArtifact` (DOM, accessibility tree, styles, screenshot,
  network log).
- `runAxe` injects `axe-core` into that page and returns its bucketed
  results.
- Proven against a fixture with a deliberate contrast violation: one
  correct, authoritative `color-contrast` finding, zero false
  positives on a clean fixture — see
  [`node-worker/test/render-axe.test.mjs`](node-worker/test/render-axe.test.mjs).
- The Python orchestrator's data models and RPC client are built and
  tested independently.

Not yet built: the ML agents, calibration, and report generators.
`verity/orchestrator/main.py`'s scan pipeline also doesn't call
`render`/`runAxe` correctly yet — see the note in
[`verity/orchestrator/README.md`](verity/orchestrator/README.md).
This README will grow a demo, an install path, and a limitations
table once there's more to show — see [docs/adr/](docs/adr/) and each
directory's own `README.md` for current state.

## Layout

```
.
├── node-worker/          # TypeScript: JSON-RPC worker over stdio (Playwright, axe-core)
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
files to it.

## How to work in this repo

Two people, two languages, one repo. The split is by directory, not by
feature — pick your language and you're in the right place.

| You are... | You work in | You run |
|---|---|---|
| **Rohan** (browser, TypeScript, CI surface) | `node-worker/` | `cd node-worker && npm test` *(builds, then runs the 15 protocol tests)* |
| **Nikhil** (orchestration, ML, Python) | `verity/`, `eval/`, `data/`, `rulepacks/` | `uv run pytest verity/tests/` |

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
  result) → **both** `node-worker/src/rpc/protocol.ts` and
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
npx playwright install chromium   # one-time: browser binary for render/runAxe
npm test                           # build + protocol suite + render/axe gate test — 17/17
```

### Python orchestrator

```bash
uv sync
uv run pytest verity/tests/
```

### Prove the cross-language contract

```bash
cd node-worker && npm run build && cd ..
python3 node-worker/contract/reference_client.py
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — setup, the shared RPC
contract, and PR conventions.

## License

[MPL-2.0](LICENSE).
