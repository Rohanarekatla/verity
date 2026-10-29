# Agent Accessibility Benchmark — results v1 (milestone M1)

**Status: AWAITING THE RUN.** This is the Week-12 gate artifact
(`docs/execution-plan.md`, Week 12 · M1). The harness is complete and tested;
the numbers below are produced, not written, and only after two preconditions
the pre-registration (`preregistration.md`) fixes:

1. **The pre-registration is signed and tagged** `agentbench-prereg-v1`
   (pre-reg §11) — the sample sizes and the budget cap are filled from the Week
   10 pilot first (`docs/measurements/agentbench-pilot.md`).
2. **Provider keys and budget are available** — `ANTHROPIC_API_KEY` /
   `OPENAI_API_KEY` for the frontier and OpenAI models, a local Ollama for the
   two local models. No run has been charged yet.

Until both hold, every table here is a placeholder with its shape fixed, so the
analysis cannot be chosen after seeing the data.

---

## How these numbers are produced

The whole run is one command, resumable and budget-capped:

```bash
uv run python -m eval.agentbench.run_benchmark \
    --model frontier=anthropic:claude-sonnet-5-5 \
    --model local-a=ollama:qwen3:8b \
    --model local-b=ollama:llama3.1:8b \
    --trials <N from pre-reg §6> --budget <cap from pre-reg §6> --workers 2 \
    --out runs/v1
```

| Piece | Module | What it guarantees |
|---|---|---|
| Runner (A12.1′) | `eval/agentbench/runner.py` | Seeded run order (`ORDER_SEED = 20261108`); resumable from `records.jsonl`; **hard budget cap**; injection verified (A11.2′) before every defect episode; a full replayable trace per episode. Computes **no** success rate during the run. |
| Results store (A12.2′) | `eval/agentbench/results_store.py` | `records.jsonl` → Parquet (lossless) + the two dashboards below, straight from the pre-registered `analysis.py`. |
| Trace viewer (A12.3′) | `eval/agentbench/trace_viewer.py` | Replays any episode step by step with the exact AXTree the agent saw — the evidence behind each number. |
| Analysis (B11.3′) | `eval/agentbench/analysis.py` | McNemar, paired-difference intervals, Holm, cluster bootstrap — the confirmatory tests, pre-registered. |

**No peeking (pre-reg §9):** success by condition is not computed until the run
is complete or the cap stops it. During the run only error rate and spend are
watched. The dashboards below are a *post-run* artifact.

---

## 0. Run manifest *(filled by the run)*

| | |
|---|---|
| Pre-registration tag | `agentbench-prereg-v1` @ `<commit>` |
| Run directory | `runs/v1/` |
| Order seed | `20261108` |
| Models | frontier `<spec>`, local-a `<spec>`, local-b `<spec>` |
| Agents | tree (A10.4). browser-use / screen-reader **not available** → H2, H3 reported *not tested* (pre-reg §2) |
| Trials per cell | `<N>` |
| Budget cap | `$<cap>` · **spent** `$<actual>` |
| Episodes | planned `<P>` · run `<R>` · excluded `<E>` |

## 1. Kill criterion check (pre-reg §9, first)

> Clean-page success for the best model: **`<x>%`**.
> Threshold: 30%. **`<PASS — proceed / FAIL — switch suite to MiniWoB++ + simplest app tasks>`.**

This is reported **before** any defect comparison is read, by rule.

## 2. Success by agent × model × defect

*Generated into `runs/v1/dashboards/dashboard.md` (and `.html`) by
`results_store.render_markdown_dashboard`. Each cell is success with a Wilson
95% interval over usable episodes, plus the exclusion count.*

| agent | model | defect | family | n | excl | success | 95% CI |
|---|---|---|---|--:|--:|--:|---|
| … | | | | | | | |

## 3. Clean vs defect — the paired effect (H1)

*From `analysis.paired_effect`: effect = success(clean) − success(defect) on
paired episodes, Bonett–Price 95% interval, exact McNemar p, Holm-adjusted
within the H1 family. A positive effect means the defect reduced success.*

| agent | model | defect | pairs | clean | defect | Δ | 95% CI | McNemar p | Holm p | supported? |
|---|---|---|--:|--:|--:|--:|---|--:|--:|---|
| … | | | | | | | | | | |

Cluster-bootstrap sensitivity (task-level, 5,000 resamples, seed `20261108`) is
reported alongside; where it disagrees with the exact test on significance,
**the conservative result is the headline** (pre-reg §8.4).

## 4. H2 / H3 — cross-agent differences

**Not tested in v1:** the browser-use (A13.1′) and screen-reader (B13.1′) agents
land in Week 13. Reported as *not tested*, never dropped (pre-reg §2).

## 5. H4 — tokens per successful task

*Secondary. Wilcoxon signed-rank on paired token totals of pairs where both
halves succeeded (`analysis.wilcoxon_signed_rank`, conditional on success), plus
tokens-per-success per cell (`analysis.tokens_per_success`).*

| agent | model | defect | pairs (both won) | clean tok/win | defect tok/win | W p |
|---|---|---|--:|--:|--:|--:|

## 6. Exclusions (pre-reg §7)

Every excluded episode, with its reason, dropped **with its pair** before any
rate. A cell losing >10% of pairs is marked **unreliable** and dropped from the
confirmatory family, with the Holm denominator adjusted and said so.

| reason | count |
|---|--:|
| `provider_error` | `<n>` |
| `budget` | `<n>` |
| `injection_unverified` | `<n>` |
| `indeterminate` | `<n>` |

## 7. Reading the evidence

Any row above can be inspected rather than trusted:

```bash
# list the episodes of one cell, then replay the interesting one
uv run python -m eval.agentbench.trace_viewer runs/v1/traces --list
uv run python -m eval.agentbench.trace_viewer runs/v1/traces \
    --episode 'tree|frontier|click-button|strip_name|t3' --html /tmp/ep.html
```

The trace shows the accessibility tree the agent saw at each step and the action
it chose — so "the defect made the task impossible" is something you read off
the tree (the button has no name), not something you take on faith.

## 8. Interpretation

*Written after the tables, against the pre-registered support rule (§8). Null
results are reported with their intervals — pre-registration is what makes a
null credible (ADR-0005). A blog post draft accompanies this gate.*
