# Agent runs: degradation and partial failure

**Week 13 artifact (both tracks).** The rule (kept from the original W13): *a
tool that quietly checks less than it claims is worse than none.* An agent run
has many ways to partially fail, and for each the report must say exactly what
was and was not measured. This document is the catalogue, and the contract the
runner and report hold to.

## The three tracks a Week-13 run produces

| Track | Question | Subject | Primary signal |
|---|---|---|---|
| Defect (A12/B12) | Does a broken page stop the agent? | tree, browser-use, (screen-reader) × models | task success, paired clean vs defect |
| Attack (A13.2′) | Does attacker text on an intact page redirect the agent? | same agents | hijack rate per (agent × attack) |
| — | How robust are *our* agents? | our agents, hardened (B13.2′) | hijack rate after hardening |

## Agent types and what each perceives

| Agent | Perceives | Acts by | Blind to |
|---|---|---|---|
| `tree` (A10.4) | the accessibility tree | element id / keyboard | pixels; visible text with no accessible name |
| `browser_use` (A13.1′) | the DOM: interactive elements + **visible text** | element id / keyboard | (vision proper pending provider image support) |
| `screen_reader` (B13.1′) | announcements only | keyboard only | anything not announced |

The perception differences are the point: a `strip_name` button is invisible to
`tree` but readable by `browser_use` (H2), and an `aria-label`-only injection is
invisible to `browser_use` but read by `tree`/`screen_reader` (A13.2′). The
report must never compare agents without stating what each could perceive.

## Ways a run partially fails — and what the report must say

| Failure | Detected by | Recorded as | The report says |
|---|---|---|---|
| Provider call failed (after retries) | `ProviderError` | episode `excluded_reason=provider_error`, dropped **with its pair** | the cell's excluded count and why; never "agent failed" |
| Budget cap reached | `BudgetExceeded` | `excluded_reason=budget`; **run stops** | which cells never ran; re-run with a higher cap to continue |
| Injection did not verify | A11.2′ `verify` | `excluded_reason=injection_unverified`; the pair never runs | that variant was not measured |
| Evaluator could not read the page | evaluators `indeterminate` | `outcome=indeterminate`, dropped with its pair | never an agent failure |
| Agent stuck in a loop | loop guard (A13.3) | episode ends; `looped=True`; `outcome=failure` | a genuine task failure, with the repeated state in the trace |
| Model emitted unparseable actions | agent parse guard | `parse_failures` counted; episode may abort | separated from task failure — a formatting problem, not a wrong click |
| Agent hijacked by injected text | canary detector (A13.2′) | `hijacked=True` | the hijack, pinned to the step that emitted the canary (see the trace) |
| Model backend killed mid-run | provider errors + resume | in-flight episode excluded; completed ones kept | the run resumes from `records.jsonl`; W13 gate: it completes and says what was not checked |

## The doctrine, unchanged

- **No model judges success or a hijack.** Task success is the env/`success:`
  evaluator; a hijack is the deterministic canary check. The maths decides.
- **An unconfirmed agent failure is never a site defect.** That confirmation is
  Week 14 (`verity agent-check`, B14.1′); until then an agent failure is a
  benchmark data point, not a WCAG finding.
- **Exclusions are reported, never hidden.** Every table carries its excluded
  count and reason; a cell losing >10% of its pairs is marked unreliable.
- **A partial run is labelled partial.** The runner never presents a
  budget-stopped or backend-killed run as complete; `RunReport` carries the
  counts and the `budget_stopped` flag.
