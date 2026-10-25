# Agent benchmark pilot (Week 10 gate) — TEMPLATE, not yet run

**Status: waiting on A10.4 (tree agent) and A10.5 (runtime injection).**
Track B's half is in place: providers + spend ledger + timing
(`eval/agentbench/providers/`) and the pilot summary
(`eval/agentbench/analysis.pilot_summary`). Fill this file from a real run;
do not edit the numbers by hand.

Pilot as planned: one tree-only agent; one local + one frontier model;
5 MiniWoB++ tasks × {clean, label stripped, div-button}; 10 trials each
(= 300 episodes). Its only job is cost and variance, so Week 12 can be sized.

## How to produce it

```
# 1. timing per provider (B10.4): load vs inference
uv run python -m eval.agentbench.providers.timing ollama:qwen3:8b
uv run python -m eval.agentbench.providers.timing anthropic:claude-sonnet-5-5

# 2. run the pilot (A10.4/A10.5 runner) with a ledger and a cap, writing
#    EpisodeRecord JSON lines to runs/pilot/episodes.jsonl

# 3. summarise
uv run python -c "from eval.agentbench.analysis import load_records, pilot_summary; import json; \
print(json.dumps(pilot_summary(load_records('runs/pilot/episodes.jsonl')), indent=2, default=str))"
```

## Results

| Provider:model | Cold load (s) | Warm inference (s/call) | Verdict |
|---|---|---|---|
| | | | |

| Agent × model × defect | Episodes | Excluded | Success (Wilson 95%) | Tokens/episode (mean ± sd) | Cost/episode |
|---|---|---|---|---|---|
| | | | | | |

| Defect vs clean (agent × model) | Pilot pairs | p10 | p01 | Pairs needed (×1.2) |
|---|---|---|---|---|
| | | | | |

**Total pilot spend:** $___ · **Proposed Week 12 cap:** $___ (plan envelope
$150–300) · **Cache-read share (frontier):** ___%

These numbers go into `docs/agentbench/preregistration.md` §6 before it is
signed.
