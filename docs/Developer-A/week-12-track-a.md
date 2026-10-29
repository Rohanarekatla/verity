# Nikhil — Week 12, Track A is in (plan v2, M1 harness)

**From Rohan.** The run harness is built and unit-tested without a browser,
network, or spend. What it needs from you to actually run is at the end — it is
short, and it is the pre-registration, not code.

## What landed

| # | What | Where |
|---|---|---|
| A12.1′ | **Runner**: enumerates the full matrix, shuffles once with `ORDER_SEED = 20261108` and records the order; resumable from `records.jsonl`; hard budget cap; verifies injection (A11.2′) before every defect episode; writes a full replayable trace per episode. Computes **no** success rate during the run. | `eval/agentbench/runner.py` |
| A12.2′ | **Results store + dashboards**: `records.jsonl` → Parquet (lossless round-trip), plus a Markdown and a self-contained HTML dashboard (success by agent × model × defect, and the paired clean-vs-defect gap) — all from your `analysis.py`, no new statistics. | `eval/agentbench/results_store.py` |
| A12.3′ | **Trace viewer**: replays any episode step by step with the exact AXTree the agent saw and the action it chose; terminal or HTML; lists/finds by episode id. | `eval/agentbench/trace_viewer.py` |
| — | CLI + the M1 gate artifact (template, awaiting the run) | `eval/agentbench/run_benchmark.py`, `docs/agentbench/results-v1.md` |

## The four properties the runner guarantees (and the one it refuses)

1. **Seeded order.** The run order is derived from the plan and `ORDER_SEED`,
   not from dict/enumeration order — I sort by `episode_id` before shuffling, so
   the same episode set always runs in the same order. Pre-reg §3.
2. **Resumable + idempotent.** The records file *is* the manifest; a re-run
   skips completed `episode_id`s and the ledger re-reads its spend. A crash or a
   budget stop continues from where it stopped — no double counting, no fresh
   budget.
3. **Hard cap.** `BudgetExceeded` → the refused episode is recorded `budget` and
   the run stops. One worker = exact cap. `--workers N` gives each worker a
   ledger capped at `cap/N`, so the sum still can't exceed the cap (a cheap
   shard can't lend slack to an expensive one — documented tradeoff).
4. **Verified injection.** A defect episode runs only after
   `verify_injection.verify` passes; otherwise it is recorded
   `injection_unverified` and skipped — its pair never runs (pre-reg §7.3).

**Refused: no peeking.** The runner never computes success by condition while
running — only error rate and spend. Success rates come from your `analysis.py`,
post-run, off the records. Pre-reg §9.

## The contract between us (unchanged, as you asked)

I write exactly one `analysis.EpisodeRecord` per episode to
`runs/<v>/records.jsonl` — the only thing your analysis reads. Excluded episodes
carry `excluded_reason` (`provider_error` | `budget` | `injection_unverified`)
and are dropped with their pair before any rate. An agent that honestly
`report_infeasible`s is a task **failure**, not an exclusion — the defect making
the task impossible is the effect we're measuring, not an error.

One decision I made that you should sanity-check: **MiniWoB success = raw reward
> 0** (`runner.SUCCESS_MIN`), because WOB's reward is time-discounted into
(0, 1] on a solve. A vendored app would carry its own `success:` evaluator
instead. If you'd rather the env-reward evaluator use `min = 1.0` strictly, say
so — it's one constant.

## What it needs from you to run (not code)

| Needs | Why |
|---|---|
| **Pre-registration signed + tagged** `agentbench-prereg-v1` | §6 sample sizes and the budget cap come from the Week-10 pilot first; nothing runs before the tag (plan v2 rule 2). I've filled the §0/§1 manifest shape in `results-v1.md`; the pilot numbers and your signature are the gaps. |
| **The pilot numbers** (`agentbench-pilot.md`) | `--trials` and `--budget` are read straight from them. |

Keys/budget are an operator step at run time (`ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / local Ollama). Once the tag is in, the whole run is one
`run_benchmark` command and the dashboards fill `results-v1.md`.

## Questions for you

- H2/H3 need the browser-use (A13.1′) and screen-reader (B13.1′) agents, which
  are Week 13. The runner takes them through `agent_factory` with no change; I've
  marked both **not tested** in `results-v1.md` §4 for v1. Agreed?
- Parquet is the derived copy; `records.jsonl` stays the source of truth your
  analysis reads. If you want the notebook to read Parquet directly instead,
  `results_store.read_parquet` returns the same records — your call.
