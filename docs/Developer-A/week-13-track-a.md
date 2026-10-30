# Nikhil — Week 13, Track A is in (plan v2: more agents, agent security)

**From Rohan.** Built and unit-tested without a browser, network, or spend. The
runner now carries three agent types and a second (attack) track, and both
share the one control loop so your screen-reader agent slots in with no runner
change.

## What landed

| # | What | Where |
|---|---|---|
| A13.1′ | **browser-use agent** (DOM-driven): perceives interactive elements + their *visible text*, so it routes around name defects the tree agent is blind to (H2). Wired into the runner. | `eval/agentbench/agents/browser_use_agent.py`, `env.observe_dom()` |
| A13.2′ | **Injection-attack track** (WASP-style): three vectors (`visible_banner`, `hidden_aria`, `fake_status`), deterministic hijack scoring by canary token, per-(agent × attack) hijack rate; resumable, budget-capped runner. | `eval/agentbench/attacks.py`, `attacks.js`, `runner.run_attack_track` |
| A13.3 | **State labelling + loop guard**: a stuck agent ends its episode as a task failure instead of burning the step budget. Wired into every agent. | `eval/agentbench/loop_guard.py` |
| — | Degradation catalogue (W13 "both" artifact) | `docs/degradation.md` |

## One refactor you'll touch

The per-episode control loop now lives in **`tree_agent.run_episode(...)`** — one
loop, parameterised by `(system prompt, observe callable)`. `TreeAgent` and
`BrowserUseAgent` are thin wrappers over it. So **B13.1′ screen-reader agent**
is: a system prompt, `observe=lambda e: e.observe_announcements()` (your virtual
SR, B9.2), and a registry line. Add it to `runner.AGENTS = {"tree":…,
"browser_use":…}` and it runs in both tracks — nothing else changes.

```python
from eval.agentbench.agents.tree_agent import run_episode
class ScreenReaderAgent:
    def run(self, env, task, seed, defect=None, attack=None):
        return run_episode(self.provider, env, task, seed, defect, attack,
                           system=_SR_SYSTEM, observe=lambda e: e.observe_announcements(),
                           loop_guard=self.loop_guard)
```

## The contracts

- **Agent result** is unchanged (`TreeAgentResult`), now with `looped: bool` set
  when the loop guard ended the episode. The runner records a looped episode as
  `outcome=failure` (a genuine failure), never an exclusion.
- **Hijack track** writes `attacks.HijackRecord` to `out_dir/hijacks.jsonl`
  (+ a replayable trace per episode). `attacks.hijack_rate(records)` gives the
  per-cell table. A hijack is the canary check — **no model judges it**, same
  doctrine as success.
- **Perceivability** is declared per attack (`Attack.perceivable_by`) so a 0%
  hijack rate is interpretable: did the agent resist, or never see the injection?
  Your SR agent reads the tree, so it perceives `hidden_aria` — that's the
  headline contrast with `browser_use` (which does not).

## Questions for you

1. **Vision proper.** `browser_use` is DOM-driven today; true vision (screenshot
   → VLM) needs image input in the provider layer (`complete()` is text-only).
   Do you want to add an `images=` channel to `providers/base.py`, or keep
   browser-use DOM-only for v1? The H2 signal (visible text the tree loses) is
   already there either way.
2. **Hardening (B13.2′).** The attack track measures hijack rate; your
   plan-then-execute / untrusted-content defences are measured *against* it. The
   browser-use prompt already tags page content as data, not commands — tell me
   if you want that wording standardised across agents so the comparison is
   clean.
3. **SR observation method name** — I assumed `env.observe_announcements()`. If
   your virtual SR exposes something else, say so and I'll leave the hook as you
   name it.
