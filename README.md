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

Early. The RPC skeleton between the two languages exists and is
tested end to end; the data models are defined; the ML agents,
calibration, and report generators described below are not yet built.
This README will grow a demo, an install path, and a limitations
table once there's something real to show — see
[docs/adr/](docs/adr/) and each directory's own `README.md` for
current state.

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

## Getting started

### Node worker

```bash
cd node-worker
npm install
npm run build
node --test test/protocol.test.mjs   # 15/15
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
