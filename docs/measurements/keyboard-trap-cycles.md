# A4.2 — how many cycles before a "no keyboard trap" verdict is trustworthy

**Measured 2026-10-17, headless Chromium (Playwright), on the Week-4 keyboard
fixtures.** This file exists because the plan requires N — the number of full
Tab cycles the traversal runs before a no-trap result is trusted — to be
*determined by measurement, not guessed*. `cyclesRequested` defaults to the N
chosen here; `agents/keyboard.py` turns `cycles_completed < cycles_requested`
into `indeterminate` rather than `pass`.

## What N has to balance

A keyboard trap (SC 2.1.2) is "focus goes in, keyboard can't get it out". The
naive check is one pass of Tab. The failure of one pass is a **state-dependent
trap**: a handler that only traps on the second encounter, or a widget whose
focus order changes after it has been cycled once. A single pass that comes
back clean has not proven such a page is trap-free — it has proven the trap did
not fire on pass one. So N must be ≥ 2 to have any margin. Against that: every
extra cycle is traversal time on every scanned page, so N must not be large for
its own sake.

## Measurement

### Detection latency — does a real trap show up, and how fast?

`keyboard-trap.html` (an input whose keydown handler eats Tab):

| cyclesRequested | trap_detected | cycles_completed | stops before trap |
|---|---|---|---|
| 1 | **true** | 0 | 2 |
| 2 | **true** | 0 | 2 |
| 3 | **true** | 0 | 2 |

The trap is caught on the **first** encounter — focus lands on the trapping
element and the next four Tab presses do not move it (`TRAP_REPEAT_THRESHOLD`),
so detection never needs a second cycle. Raising N does not delay or change
detection. **N is not driven by detection latency.**

### False-alarm check — does a clean widget complete its cycles?

`keyboard-tablist.html` (a correct roving-tabindex tablist):

| cyclesRequested | trap_detected | cycles_completed | returned_to_origin | complete |
|---|---|---|---|---|
| 1 | false | 1 | true | true |
| 2 | false | 2 | true | true |
| 3 | false | 3 | true | true |

A clean page completes exactly the cycles requested and returns to origin each
pass. This is the property that matters: if a clean page could *not* complete N
cycles, raising N would turn every clean page into `indeterminate`. It can, so
N costs nothing in false alarms.

### Cost per cycle

Median wall-clock for the full `traverseTabOrder` call on the tablist (3 runs
each):

| cyclesRequested | median |
|---|---|
| 1 | 21 ms |
| 2 | 20 ms |
| 3 | 42 ms |
| 5 | 41 ms |

Tens of milliseconds across the useful range — negligible against a render
(hundreds of ms) and an axe run (seconds). Cost does not constrain N either.

## Decision

**N = 2** (the default `cyclesRequested`).

Neither detection latency nor cost drives the number — a real trap is caught on
cycle 1 and cycles are nearly free. N = 2 is chosen for the one thing a single
pass cannot give: a **second, independent pass** over a page whose focus
behaviour may depend on having been traversed once. It is the smallest N that
provides that margin, and the measurement shows a clean page completes it every
time, so it buys the margin at zero false-alarm cost.

Callers may raise `cyclesRequested` for a specific suspect page; the verdict
stays honest because `cycles_completed` is reported and a short run degrades to
`indeterminate`, never to a false `pass`.

## Threats to this result

- Headless Chromium wraps focus to `document.body` at the end of a pass rather
  than to a browser chrome and back; the traversal treats that body-landing as
  the cycle boundary. A headed browser or a different engine may wrap
  differently. Re-measure if the traversal is ever run outside headless
  Chromium.
- The fixtures are small. A page with hundreds of stops has not been measured
  here; the per-cycle cost is linear in stop count, so N = 2 doubling that cost
  stays acceptable, but a very large real page is worth re-timing before Phase 2
  performance work (Week 17).
