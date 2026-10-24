# Agent Accessibility Benchmark — pre-registration (v1)

**Status: DRAFT (Track B, B11.3′, 24 Oct 2026). Not yet signed.** Becomes
binding when both engineers sign below and the commit is tagged
`agentbench-prereg-v1` — **before any Week 12 run** (plan v2, rule 2). Fields
marked **[PILOT]** are filled from `docs/measurements/agentbench-pilot.md` (the
Week 10 gate) before signing; nothing else may change after the tag except
through the deviation procedure (§10).

Analysis code: `eval/agentbench/analysis.py` (pure standard library),
driven by `eval/agentbench/analysis.ipynb`. Success: `eval/agentbench/evaluators.py`.

---

## 1. Question

Do WCAG defects change the task success of AI web agents — which defects, by
how much, for which kind of agent? (ADR-0005.) No controlled measurement of
this exists; practitioner claims assert the link without data.

## 2. Hypotheses

| # | Hypothesis | Confirmatory test | Direction |
|---|---|---|---|
| H1 | Name defects — missing label, empty button, div-as-button — reduce **tree-only** agent success | Per (defect × model): paired clean vs defect success, exact McNemar; Holm across the H1 family | clean > defect |
| H2 | Vision-capable agents are **less** affected than tree-only agents by the same name defects | Per (defect × model): difference-in-differences (tree effect − vision effect), task-cluster bootstrap 95% CI | DiD > 0 |
| H3 | Keyboard traps and focus defects hurt the **screen-reader** agent most | Per (defect × model): DiD (screen-reader effect − tree effect), cluster bootstrap 95% CI | DiD > 0 |
| H4 | Accessible pages cost **fewer tokens per successful task** | Per (agent × model × defect): tokens/success, clean vs defect, cluster bootstrap 95% CI of the ratio | clean < defect |

"Effect" throughout = success(clean) − success(defect) on paired episodes.

H2 and H3 depend on agents delivered in Week 13 (A13.1′ browser-use, B13.1′
screen-reader agent). If either agent is not available by the run, that
hypothesis is reported as **not tested**, never dropped silently.

## 3. Design

- **Unit:** one episode = one agent attempting one task once, up to a step
  cap.
- **Factors:** task (A11.1′ suite: 20–30 tasks over 2–3 pinned vendored apps
  + MiniWoB++ families) × defect (clean + the defects in §4) × agent (tree,
  browser-use, screen-reader) × model (2 local via Ollama, 1 frontier) ×
  trial.
- **Pairing:** each defect episode is paired with the clean episode of the
  same (task, agent, provider, model, trial). The trial index fixes the
  episode seed for providers that accept one (Ollama, OpenAI). Claude
  (API version 2026-10-21) accepts no sampling parameters at all, so its
  pairs share task and order but not a seed — its variance is measured, not
  controlled.
- **Injection:** at page load, from `eval/inject`, and **verified** by Verity
  before the episode (A11.2′): exactly the intended defect, nothing else. A
  variant that fails verification is aborted and logged — never run.
- **Order:** episodes are run in an order randomised once with seed
  `20261108` and recorded, so time-of-day and provider drift cannot align
  with a condition.

## 4. Defects (fixed at signing)

| Family | Defect id (`eval/inject`) | Used in |
|---|---|---|
| name | `strip_accessible_name` (empty button / link) | H1, H2, H4 |
| name | `click_only_widget` (div-as-button) | H1, H2, H4 |
| name | `detach_label` (missing form label) | H1, H2, H4 |
| keyboard | `keyboard_trap` | H3, H4 |
| keyboard | `remove_from_tab_order` | H3, H4 |
| focus | `outline_none` | H3, H4 |

Prevalence context (WebAIM Million 2026): low contrast 83.9%, missing alt
53.1%, missing labels 51%, empty links 46.3%, empty buttons 30.6%. Contrast is
deliberately **not** a v1 defect: a tree-only agent cannot perceive it, so it
would test nothing about agents, only the obvious.

## 5. Outcomes

**Primary:** task success, decided by the task's deterministic evaluator
(`success:` block: URL, element state, localStorage, the app's API or DB, or
BrowserGym's reward). **No model judges success.** Every evaluator must report
`failure` on the task's start state and `success` on its solved state
(`verify_evaluator`) before the task enters the suite.

**Secondary:** steps to completion; total tokens (input + output + cache
read + cache write); cost (USD, from the provider ledger); tokens per
successful task (H4).

## 6. Sample size **[PILOT]**

Pairs per (defect × agent × model) cell from the pilot's observed discordance
(`analysis.mcnemar_pairs_needed`, Connor 1987), α = 0.05 two-sided, power 0.8,
×1.2 margin for the exact test's conservatism and for exclusions:

| Cell | Pilot p10 | Pilot p01 | Pairs needed | Trials per task |
|---|---|---|---|---|
| tree × local model × div-button | [PILOT] | [PILOT] | [PILOT] | [PILOT] |
| tree × frontier model × div-button | [PILOT] | [PILOT] | [PILOT] | [PILOT] |
| … | | | | |

If the pilot shows no discordance in a cell (p10 = p01), the **planning
effect** is a 15-point drop (p10 = 0.20, p01 = 0.05 → 85 pairs before margin,
102 after),
stated here so the number is not chosen after the fact.

**Budget cap [PILOT]:** $___ total, enforced by the provider ledger before
every call (worst case per call; a run stops, it never overspends). If the
cap would be reached before the planned N, frontier-model cells are cut to the
capped subset **in the order listed in §4**, and the shortfall is reported.

## 7. Exclusions (decided now, applied by code)

An episode is excluded — **with its pair** — if any of:

1. the provider call failed after bounded retries (`provider_error`);
2. the budget cap refused a call (`budget`);
3. the injected variant failed verification (`injection_unverified`) — the
   pair never runs;
4. the evaluator returned `indeterminate` (the page or app could not be
   read) — never counted as an agent failure.

Every results table reports the number excluded and why. If more than 10% of
a cell's pairs are excluded, that cell is reported as **unreliable** and
excluded from the confirmatory family (with its Holm denominator adjusted and
said so).

## 8. Analysis

1. Per cell: success with Wilson 95% interval.
2. Per comparison: paired 2×2 table, exact McNemar p, paired difference with
   Bonett–Price adjusted-Wald 95% interval.
3. Multiplicity: Holm–Bonferroni within H1 (all defect × model cells). H2–H4
   are interval estimates; they are interpreted only if H1 is supported for
   the same defect.
4. Sensitivity: trials within a task are correlated, so every primary result
   is repeated with a task-level cluster bootstrap (5,000 resamples, seed
   `20261108`). Where the two disagree on significance, both are reported and
   the conservative one is the headline.
5. H4 secondary: Wilcoxon signed-rank on paired token totals of pairs where
   both halves succeeded (explicitly conditional on success).

**Support** for H1 in a cell: Holm-adjusted p < 0.05 **and** interval
excludes 0 in the predicted direction. A significant effect in the opposite
direction is reported as such. **Null** results are published with their
intervals — pre-registration is what makes a null credible (ADR-0005).

## 9. Kill criterion and stopping

- If clean-page success for the best model is < 30% (ADR-0005), the suite
  switches to MiniWoB++ + the simplest app tasks; this is announced before any
  defect comparison is looked at.
- **No peeking:** success rates by condition are not computed until every
  planned episode is complete or the cap stops the run. Monitoring during the
  run is limited to error rates and spend.

## 10. Deviations

Any change after the tag is a new commit to this file under "Deviations",
with date, what changed, why, and whether it was made before or after seeing
outcome data. Results produced under a deviation are labelled with it.

### Deviations

*None.*

## 11. Signatures

- Nikhil (Track B, author) — ____________ date ______
- Rohan (Track A) — ____________ date ______

Tag after both: `git tag -a agentbench-prereg-v1 -m "Pre-registration v1" && git push origin agentbench-prereg-v1`
