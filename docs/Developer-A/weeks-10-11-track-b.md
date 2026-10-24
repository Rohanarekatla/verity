# Rohan — Weeks 10–11, Track B is in (plan v2)

**From Nikhil.** Everything below is built and unit-tested without network or
API keys. What is still blocked is blocked on Track A, and is listed at the
end — please read that part first.

## What landed

| # | What | Where |
|---|---|---|
| B10.3′ | Provider layer: Anthropic, OpenAI (+ any OpenAI-compatible), Ollama behind one `complete()` | `eval/agentbench/providers/` |
| B10.3′ | Token + cost accounting per call; prices with sources in `pricing.yaml` (checked 24 Oct) | `pricing.py`, `pricing.yaml` |
| B10.3′ | Prompt caching (Anthropic: system breakpoint + automatic; OpenAI: automatic, `prompt_cache_key`) | `anthropic.py`, `openai.py` |
| — | **Hard spend cap**: `CostLedger(cap_usd, path)` refuses a call *before* sending it if its worst case could cross the cap; resumes from disk | `ledger.py` |
| B10.4 | Load vs inference timing per provider (Ollama reports load/prompt/generate; remote = wall only) | `timing.py` |
| B11.1′ | Deterministic success evaluators: url / element / localStorage / app API / SQLite (read-only) / env reward; three-state; no LLM | `eval/agentbench/evaluators.py` |
| B11.2′ | Schema linter: every closed vocabulary in an output model is classified; judgments carry an escape; JSON-Schema mode for anything handed to a model | `verity/schema_lint.py`, `test_schema_lint.py` |
| B11.3′ | Pre-registration draft + analysis code + notebook | `docs/agentbench/preregistration.md`, `eval/agentbench/analysis.py`, `analysis.ipynb` |
| — | Pilot template (W10 gate doc) | `docs/measurements/agentbench-pilot.md` |

B10.1–2 (OCR / grounding) are **optional** in plan v2, behind the ADR-0002
flag, and I have not done them — the vision descope still stands and nothing
gates on them. Say if you want one done for the Readiness Report.

## Three things you should know before wiring the tree agent

1. **Claude API version 2026-10-21 rejects `temperature`/`top_p`/`top_k`**
   with a 400, even at defaults. The provider sends none. So Claude episodes
   cannot be seeded or cooled; their variance is measured, not controlled.
   This is in the pre-registration (§3).
2. **Provider errors raise `ProviderError`; they do not return empty text.**
   Unlike the vision backends, a failed call must become an *excluded
   episode*, not an agent that "did nothing". `BudgetExceeded` is a subclass —
   catch it to stop the run cleanly.
3. **Keys never appear in a `Completion`, an error, or the ledger.** Please
   keep it that way in traces (S20.1).

## The contracts you consume

```python
from eval.agentbench.providers import make_provider, CostLedger, Message
ledger = CostLedger(cap_usd=CAP, path=run_dir / "ledger.jsonl")   # resumable
llm = make_provider("ollama:qwen3:8b", ledger=ledger)              # or anthropic:claude-sonnet-5-5
out = llm.complete([Message(role="user", content=obs)], system=PROMPT, max_tokens=256,
                   seed=trial, cache_key=task_id, tag=episode_id)
out.text, out.usage, out.cost_usd, out.timing

from eval.agentbench.evaluators import observation_from_page, evaluate
obs = observation_from_page(page, task["success"], env_reward=reward)   # sync Playwright (BrowserGym)
result = evaluate(task["success"], obs, task_id=task["id"])             # success | failure | indeterminate
```

The runner writes one `eval.agentbench.analysis.EpisodeRecord` per episode
(JSON lines). That record is what the analysis reads — nothing else — so if
you need another field, add it there and tell me.

## Blocked on Track A

| Needs | For | Why |
|---|---|---|
| **A10.4** tree agent | the **W10 pilot** (joint artifact) and its gate | the pilot is the agent running; I can't produce tokens/episode without it |
| **A10.5** runtime injection | the pilot's {label stripped, div-button} variants | defects at page load |
| **A11.1′** task suite | per-task `success:` blocks (B11.1′'s "per task" half) | I built the evaluator; the tasks are yours. Each task should ship a start state and a solved state so `verify_evaluator` can prove its evaluator can fail and can pass (the A9.4 rule for tasks) |
| **A11.2′** injection verification | the W11 gate | "every (task × defect) cell has a verified injection" |

When the pilot has run, `pilot_summary()` fills
`docs/measurements/agentbench-pilot.md`, and its sample sizes go into the
pre-registration §6. Then we sign and tag it together (the W11 pair item).

## Questions for you

- The agent's **action schema** (BrowserGym actions) should go through
  `lint_json_schema(schema, escapes={"report_infeasible"})` — is
  `report_infeasible` the escape you plan to expose? Without one, the agent is
  forced to act when it should give up, which is the fabrication trap in
  action form.
- Pre-registration §4 fixes six defects. Do you agree with leaving contrast
  out of v1 (a tree-only agent cannot perceive it)?

Also: ADR-0005's signature line still asks for my written confirmation —
I'll add it on the PR.
