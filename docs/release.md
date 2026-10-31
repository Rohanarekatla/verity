# Release checklist (S20.1–S20.5)

The published artifacts are the **tagged repository**, the **Docker image**
(`deploy/Dockerfile` — Python, Node and Chromium in one image, so nothing has
to be installed beside it) and the **GitHub Action** (`action/`). A `pip`
wheel is deferred: Verity is a two-runtime system (Python + a built Node
worker + Chromium), and a wheel that silently lacks the worker would install
and then fail — the image is the honest installable artifact for 1.0.

| # | Step | Command / check | Done |
|---|---|---|---|
| 1 | Tests green on a clean checkout | `uv sync && (cd node-worker && npm ci && npm run build) && uv run pytest` | ☐ |
| 2 | Security pass — no secrets in repo or run outputs | `uv run python -m eval.security_scan . runs/` (exit 0; screenshots listed are checked by a person) | ☐ |
| 3 | Dependency audit | `cd node-worker && npm audit --omit=dev`; `uvx pip-audit` | ☐ |
| 4 | Licence ledger has no UNVERIFIED row in use | `docs/licenses.md` | ☐ |
| 5 | Rule packs verify | `uv run python -m verity.cli rules verify rulepacks/` | ☐ |
| 6 | Precision/recall vs frozen baseline | `uv run python -m eval.precision_recall --check 0.1.0` | ☐ |
| 7 | Outside-person install from README alone | a person outside the project, notes in `docs/measurements/outside-install.md` | ☐ |
| 8 | Docker image builds and runs | `docker build -f deploy/Dockerfile -t verity:1.0.0 .` then `docker run --rm verity:1.0.0 scan https://example.com` | ☐ |
| 9 | Tag and publish | `git tag -a v1.0.0 -m "Verity 1.0.0" && git push origin v1.0.0`; push the image; GitHub release notes | ☐ |
| 10 | ACT report per ADR-0010 | `eval/act_runner.py` + EARL | ☐ |
| 11 | Benchmark data + paper + Readiness Report | `docs/paper/`, `docs/agentbench/data-card.md`, `runs/readiness/report.md` | ☐ |
| 12 | Retrospective signed | `docs/retrospective.md` | ☐ |
| 13 | Launch posts (S20.4 v2) | Show HN, r/webdev, r/accessibility, LinkedIn, dev.to; web.dev / Chrome DevRel / WebAIM | ☐ |
