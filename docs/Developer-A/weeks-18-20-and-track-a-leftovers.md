# Rohan — what I finished while you were out of usage (30 Oct)

**From Nikhil.** You were blocked, so I finished the remaining Track A items
and the shared Weeks 18–20 work. Please review — anything you would have done
differently, change it.

## Your track (A)

| What | Where |
|---|---|
| **H3 is now testable**: `keyboard_trap`, `remove_from_tab_order`, `outline_none` as runtime defects (pixel-invisible until the keyboard is used) | `eval/agentbench/defects.js` |
| Their verification: a **Tab probe** on clean vs defect (`tab_probe` + pure `assess_keyboard`); the tree comparison refuses keyboard defects | `eval/agentbench/verify_injection.py` |
| Applied to 5 tasks (one+ per family); families in `DEFECT_FAMILY`; `test_week11_benchmark` updated for six defects | `tasks.py`, `runner.py` |
| **Cache invalidation**: `ruleset_fingerprint()` (Verity + axe-core version, every contract, validator version, focus-visible flag, waivers). `crawl_site` uses it when no `ruleset_version` is passed | `verity/crawl/cache.py`, `site.py` |
| GitHub Action: `agent-task` / `agent-success` / `agent-model` inputs run `agent-check --confirm`, upload a second SARIF, gate only on a confirmed defect | `action/action.yml` |

## Shared Weeks 18–20

| Week | What | Where |
|---|---|---|
| 18 | Paper draft (results sections marked [RUN]) | `docs/paper/agent-accessibility-benchmark.md` |
| 18 | Demo: page + one-command script + recording script | `data/demo/checkout/`, `eval/demo.py`, `docs/demo-script.md` |
| 19 | Licence ledger from the actual licence files (UNVERIFIED rows listed) | `docs/licenses.md` |
| 19 | README rewritten (install, commands, what it checks, honest limits); limitations table; data card | `README.md`, `docs/limitations.md`, `docs/agentbench/data-card.md` |
| 19 | Contributing: mandatory fixtures for every kind of check | `CONTRIBUTING.md` |
| 19 | **Community rule packs** with a fixture gate + sandboxed Python rules; never gate; `verity rules verify`, `scan --rules` | `verity/plugins.py`, `rulepacks/` |
| 20 | Security pass script (repo + run outputs; 0 secrets found today) | `eval/security_scan.py` |
| 20 | Release checklist (Docker image = installable artifact for 1.0), retrospective, ADR-0010 (proposed) | `docs/release.md`, `docs/retrospective.md`, `docs/adr/0010-act-submission.md` |

Dependencies added: `pyarrow` (your results store) and the Python `playwright`
package (your agent env imports it; it was never declared).
