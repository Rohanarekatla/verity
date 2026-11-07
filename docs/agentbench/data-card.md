# Data card — Agent Accessibility Benchmark v1

*(Plan v2, Week 19: "the benchmark's data card". Fields marked [RUN] are filled
from the pre-registered run.)*

## What the data is
One JSON line per agent episode (`analysis.EpisodeRecord`): task, app, defect
(or `clean`), defect family, agent type, provider, model, trial, seed, outcome
(`success` / `failure` / `indeterminate`), exclusion reason, steps, tokens
(input, output, cache read, cache write), cost in USD. A Parquet copy is
derived from it. One replayable trace per episode holds the exact
accessibility tree (or DOM / announcements) the agent saw at each step, the
action it chose, and any error. The attack track adds one `HijackRecord` per
episode.

## How it was produced
- **Pages:** MiniWoB++ tasks (vendored at a pinned commit, not redistributed
  here) **[RUN: commit]**; defects injected at page load by
  `eval/agentbench/defects.js`.
- **Verification:** a variant is used only if the defect manifested (tree
  change, or a Tab probe for keyboard defects) and the static render is
  pixel-identical to clean (`verify_injection.py`).
- **Agents and models:** see the pre-registration §3; model versions and
  provider API versions are recorded per episode **[RUN]**.
- **Success:** the environment's own reward or a deterministic evaluator — no
  model judges outcomes.
- **Order and budget:** seeded run order (20261108); hard spend cap; spend in
  the ledger files.

## Intended use
Measuring how specific WCAG defects change web-agent task success, and
reproducing or extending that measurement. Not a ranking of models in general
— the tasks are small, synthetic web tasks.

## Known limitations and biases
Small task pages; English only; Chromium only; frontier models could not be
seeded (API 2026-10-21 rejects sampling parameters); a simulated screen reader,
not a real one; contrast defects excluded by design. Exclusions are reported
per cell, and cells losing >10% of pairs are marked unreliable.

## Personal data
None. Pages are synthetic; no user data is collected. Traces are scrubbed of
credentials (`verity/crawl/auth.scrub_secrets`, `eval/security_scan.py`).

## Licence
Data: CC BY 4.0 **[to confirm at release]**. Code: MPL-2.0. MiniWoB++ under its
own licence (see `docs/licenses.md`).

## Maintenance
Versioned with the pre-registration tag (`agentbench-prereg-v1`); any rerun
with a deviation is a new version with the deviation listed.
