# Kill-criteria retrospective (S20.4)

*Status: written 2026-10-30, before the benchmark runs. Rows marked **[RUN]**
are completed from the measured results; nothing here is filled in by hope.
Final version is signed by both engineers at the Week 20 gate.*

The plan set every bar **before** the work, so a slip could not be argued away
afterwards. This records which fired, which did not, and what the bars caught.

| Gate / kill criterion | Pre-set bar | Outcome | What it caught |
|---|---|---|---|
| Spike A — vision precision (23 Aug) | the precision bar agreed in advance (`docs/measurements/precision-bar.md`) | **FIRED** — the 8B model abstained on 79% of cases; zero false positives but almost no findings | Vision was descoped to a flag-gated experiment (ADR-0002) instead of four weeks of productionising a capability with near-zero recall; Phases 3–5 were re-planned around agents (ADR-0005) |
| Contrast-over-image beats axe at zero new FP (6 Sep) | recall > axe, FP = 0 | **passed** — 202/202 decided, 0 false (BC-C2) | — |
| Trap detected, zero false alarms (13 Sep) | N cycles chosen by measurement | **passed** (`docs/measurements/keyboard-trap-cycles.md`) | the roving-tabindex false alarm, found by writing the tablist contract first |
| No finding without provenance (4 Oct) | type invariant | **passed** — enforced at construction (B6.2) | a `cantTell` finding claiming full deterministic confidence (Week 2 bug), now unconstructable |
| Baseline isolates new findings (11 Oct) | 50 old + 1 new fails on exactly 1 | **passed** (B7.4 tests) | — |
| Five APG contracts, misuse fails, zero false alarms (25 Oct) | 0 FP on reference implementations | **passed** on fixtures + injected misuse; reference-page run: 0 failures on 8 pages before dialog/combobox — **[RUN]** for the 5 added pages | two checker false alarms on APG's own examples (action buttons in tabs; activedescendant menus), fixed before ship |
| Pilot measured cost + variance (1 Nov, v2) | pilot recorded | **[RUN]** | — |
| Pre-registration tagged before any run (8 Nov, v2) | tag exists before W12 | **[RUN]** | the defect ids in the draft did not match the runner's; fixed before signing |
| Benchmark floor (15 Nov, v2) | best model ≥ 30% clean success | **[RUN]** | — |
| agent-check: 0 wrong confirmations (29 Nov, v2) | 0 on the injected corpus | **[RUN]** — confirmations ship off by default until measured | — |
| Fix loop ≥ 60%, 0 accepted regressions (6 Dec, v2) | both | **[RUN]** | acceptance requires a regression-free baseline diff by construction; checked independently |
| 25-page audit within CI budget (20 Dec) | budget | **[RUN]** | a missed cache invalidation (`ruleset_version` was a constant) — fixed with a ruleset fingerprint |
| Outside install from README (3 Jan) | a person outside the project | **[RUN]** — must be an outside person | — |

## What we would do differently

- Write the contract / rubric / pre-registration **before** the code every
  time — each time we did, it caught a false alarm or a mismatch for free.
- Keep a release-time dependency check from day one: `pyarrow` and the Python
  `playwright` package were used by code before they were declared.
- Never squash-merge long-lived branches without re-merging main promptly: the
  broken ancestry cost several conflict-resolution sessions.
