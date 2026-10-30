# Rohan — Weeks 12–17, Track B is in

**From Nikhil.** Everything below is built and unit-tested without a browser,
network, API keys or spend. The parts that need those are listed at the end as
**operator runs** — they are commands, not code.

## What landed

| Week | # | What | Where |
|---|---|---|---|
| 12 | B12.2′ | Pre-registered results tables: kill check first, H1 (McNemar, Holm, Bonett–Price + cluster bootstrap, *unreliable* cells leave the family), H2/H3 DiD, H4, exclusions | `eval/agentbench/report_v1.py` |
| 12 | B12.3′ | Cost model: $/episode, $/successful task (failures charged), tokens/step, × clean | same |
| 13 | B13.1′ | **Screen-reader agent**: hears only announcements (virtual SR, B9.2), acts only by keyboard — enforced, a click is refused by the env | `eval/agentbench/agents/screen_reader_agent.py` |
| 13 | B13.2′ | **Hardening**: untrusted-content fence, plan-then-execute (plan from the goal alone), allow-list + data-flow rule enforced in the env (typed text must come from the goal); `hardening_effect` pairs baseline vs hardened per attack | `eval/agentbench/hardening.py` |
| 13 | B13.3 | `verity-trace.json` (`scan --trace`), a **coverage section under every scan** (CHECKED / PARTIAL / NOT CHECKED, with why), `render_failed` in the crawl | `verity/observability.py`, `orchestrator/main.py`, `crawl/site.py` |
| 14 | B14.1′ | **Confirmation** for agent-check: two textbook rules from the live page over CDP (unnamed control; roleless clickable with a click listener and no focus); everything else needs-review. `--confirm` flag, off by default until the gate is measured. `confirmation_metrics` = the M2 gate | `verity/agent_check/confirm.py` |
| 14 | B14.2′ | **Agent-readiness score** with evidence per point; unmeasured points never count as earned; `verity readiness URL` | `verity/readiness.py` |
| 14 | B14.3 | Per-SC precision/recall on a labelled corpus (fixtures + clean twins + B9.4 misuse), **baseline freeze + `--check` exits 1 on regression**; WCAG 2.2 table (87 rows) + honest coverage metric | `eval/precision_recall.py`, `verity/standards.py` |
| 15 | B15.1′ | **Verifier-gated fix loop**: sandbox copy → exact-replacement patch → re-scan → accept only if resolved AND no new finding; ≤3 attempts, then hand-off with reasons. `LLMPatcher` (any provider) + `RulePatcher` | `verity/remediation/fix_loop.py` |
| 15 | B15.2′ | Fix eval on injected defects: fix rate, **independent** accepted-regression check, patch size, $/fix, the W15 gate | `eval/fix_eval.py` |
| 15 | B15.3 | EARL 1.0 JSON-LD (`scan --earl`), hand-written assertion first; every unjudged criterion `earl:untested` | `verity/report/earl.py`, `docs/earl-example.jsonld` |
| 16 | B16.1/B16.2 | **ACR (VPAT 2.5, WCAG 2.2)**: every row; never "Supports" from automation; AI-assisted rows labelled; unevaluated A/AA rows make it a DRAFT; human results via `--manual`; `verity acr` | `verity/acr.py` |
| 17 | B17.1′–B17.3′ | **Agent Readiness Report** pipeline: resumable site-list scan on your `crawl_site`, seeded agent-task sample with confirmation (only confirmed failures blamed on the site), report + accessible SVG figures | `eval/readiness_report.py`, `data/readiness/` |

## Changes to your files

All small; tell me if you'd rather they were done differently.

1. **`runner.py`** — `AGENTS` now has `screen_reader` and the three `*_hardened`
   variants (you asked for the registry line). `perceivable` uses the *base*
   agent (`tree_hardened` perceives what `tree` does). Hijack records carry
   `attempted`.
2. **`attacks.py`** — `assess_hijack` now counts a hijack only when the canary
   action **reached the page** (`step.ok`). A canary the guarded env refused is
   `attempted=True, hijacked=False` — otherwise hardening could never show a
   reduction. All your tests still hold (their steps are all `ok=True`).
3. **`crawl/site.py`** — a page whose render or analysis raises is recorded in
   `SiteReport.render_failed` and the crawl continues (B13.4). It used to abort
   the whole crawl.
4. **`cli.py`** — new: `scan --trace/--earl`, `agent-check --confirm`,
   `verity readiness`, `verity acr`. Nothing existing changed behaviour.

## Your questions, answered

- **W12 — MiniWoB success = reward > 0:** agree; the reward is time-discounted
  into (0, 1] on a solve. **H2/H3 "not tested":** H2 is now testable (both
  agents exist); H3 still needs keyboard/focus defects in `defects.js` +
  `verify_injection` effects — pre-reg §4 now says so, and H3 is reported *not
  tested* if they are absent at signing. `records.jsonl` stays the source of
  truth.
- **W13 — vision proper:** keep browser-use DOM-only for v1; no `images=`
  channel. **Hardening wording:** standardised in `hardening.HARDENING_RULES`;
  compare `tree` vs `tree_hardened` etc. on the attack track. **SR hook:** I did
  not add an env method — `screen_reader_agent.observe_announcements(env)` reads
  the CDP tree from `env.page`, so `env.py` is untouched.
- **W14 — agent-check without `--success`:** stay self-reported; readiness is
  its own command. **Confirmer scope:** the localised element only, two rules.
  Proof or nothing — zero wrong confirmations is the gate.
- **W15 — fix-loop interface:** in-process (`scan_url` directly), so it needs
  neither stdio nor the MCP cache. **ACT corpus:** your call; the fix eval uses
  our own injected corpus.
- **W16 — readiness weighting:** no change needed; readiness scales your score
  to 20 points, the ACR does not use it.
- **W17 — cache invalidation (my independent list):** `content_hash`,
  `ruleset_version`, `viewport` — **plus** the validator version (finding
  signatures/dedup), a digest of `waivers.yaml` (it sets `waived`), and the
  check configuration (`MEASURE_FOCUS_VISIBLE`, the contracts YAML, the axe-core
  version). Today `ruleset_version` is the constant `"1.0.0"` in `main.py`, so
  editing a contract would serve stale cached findings. Suggest: compute
  `ruleset_version` as a digest of (verity version, axe-core version, contracts
  YAML, validator version) — then the existing key covers it.

## Operator runs (need keys, money, a browser or the network)

```
# W10/W11: the pilot, then sign + tag the pre-registration together
uv run python -m eval.agentbench.run_pilot ...
# W12: the benchmark, then the pre-registered tables
uv run python -m eval.agentbench.run_benchmark ... --out runs/v1
uv run python -m eval.agentbench.report_v1 runs/v1/records.jsonl --out runs/v1/results-v1-tables.md
# W13: attack track, baseline vs hardened
run_attack_track(models, agents=("tree", "tree_hardened", "screen_reader", "screen_reader_hardened"), ...)
# W14: P/R + freeze; readiness
uv run python -m eval.precision_recall --freeze 0.1.0
uv run python -m verity.cli readiness https://example.com
# W15: fix eval (rules first, then a model)
uv run python -m eval.fix_eval --patcher rules
uv run python -m eval.fix_eval --patcher anthropic:claude-sonnet-5-5 --budget 5
# W16: ACR from saved scans
uv run python -m verity.cli acr scan1.json scan2.json --product "Demo" --out acr.md --html acr.html
# W17: the report
uv run python -m eval.readiness_report scan data/readiness/sites-sample.txt --out runs/readiness
uv run python -m eval.readiness_report agents runs/readiness --tasks data/readiness/tasks-sample.yaml --sample 5 --model anthropic:claude-sonnet-5-5 --budget 10
uv run python -m eval.readiness_report report runs/readiness
```
