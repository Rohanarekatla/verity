# Nikhil — Week 14, Track A is in (`verity agent-check`, M2)

**From Rohan.** Built and unit-tested without a browser, network, or spend. This
is the agent-check *scaffold* — run, localise, report — with the one piece it
depends on from you (confirmation, B14.1′) behind a clean seam and currently
**off**, which is exactly the Week-14 safety fallback.

## What landed

| # | What | Where |
|---|---|---|
| A14.1′ | **`verity agent-check URL --task "…" [--success "…"]`** — the tree agent attempts the task on a real page; a failure is localised to a step + control + WCAG criterion | `verity/agent_check/`, `eval/agentbench/web_env.py`, CLI subcommand |
| A14.2′ | **Reports**: JSON + SARIF (reuses `report/sarif.py`, so inline PR annotations work) + an HTML trace (reuses the Week-12 `trace_viewer`); the SARIF is the Action input | `verity/agent_check/report.py` |
| A14.3 | **Complete injector catalog (~16 types) + prevalence weighting** (WebAIM Million 2026) | `eval/inject/catalog.py`, `eval/inject/common_defects.py` |

## The safety rule, enforced in code

*An unconfirmed agent failure is never reported as a site defect.* The default
confirmer (`check.default_confirm`) returns **needs-review for every
localisation** — confirmations are OFF. So today agent-check emits needs-review
findings (SARIF `note`s that annotate but never gate), which is the gate's
fallback ("confirmations disabled until zero wrong confirmations"). Nothing can
claim a confirmed site defect until your checks say so.

## The one seam I need from you — B14.1′

`agent_check(..., confirm_fn=…)` takes a confirmer:

```python
ConfirmFn = Callable[[Localization], tuple[Provenance, Confidence, str]]
# Localization has: step, sc_id, selector, ax_node_id, observation
```

Your B14.1′ runs Verity's deterministic checks (names, contracts, traversal,
contrast) on `loc.selector` / the failing step and returns:
- `(AUTHORITATIVE, Confidence(1.0, "deterministic"), "fail")` when the defect is
  confirmed present, or
- `(NEEDS_REVIEW, …, "cantTell")` when it cannot be confirmed (the default).

Wire it in and the gate's ≥80%-localised / **zero wrong confirmations** target
becomes measurable. Until then I keep the default and nothing gates.

## Localisation — how it pins a failure (so you can confirm the right thing)

`localize_failure` reads the agent's own trace: at the stuck step (report-
infeasible / loop-guard / last step) it parses the accessibility tree the agent
saw and finds the first **nameable control with no name**, or a **roleless
clickable** (div-button) → SC 4.1.2, with `selector=[data-vbid="…"]`. That
`data-vbid` is the benchmark element id `env.observe()` assigns, so your
confirmer can target the exact element.

## A14.3 catalog — for your success evaluators / the benchmark mix

`catalog.CATALOG` is the 16 injectors with WCAG SC, family, default selector,
and WebAIM prevalence. `catalog.prevalence_weights()` gives a normalised mix
over the five WebAIM-measured defects (low contrast → empty buttons); the
agent-relevant ones (div-button, keyboard traps, roving tabindex) carry
`prevalence=None` and are excluded from the weighted mix and said so. Use the
weights to sample a realistic injector mix rather than testing every defect
equally.

## Questions

1. **Success without `--success`.** Right now, with no success spec, success is
   the agent's own `done`/`infeasible`/loop verdict (reported as
   "self-reported"). Your B14.2′ agent-readiness score is the fuller answer —
   should agent-check call into it when `--success` is absent, or stay
   self-reported and leave scoring to `verity readiness`?
2. **Confirmer scope.** Does B14.1′ confirm only the localised SC (4.1.2 today),
   or run the full check battery on the step's subtree? The seam passes the
   whole `Localization`, so either works — tell me which you're building.
