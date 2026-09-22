# Rohan — read this before you start A4.1

Follow-up to [`week-4-action-items.md`](week-4-action-items.md). Track B's
Week 4 is finished, and while writing the tablist APG contract I found
something that changes what A4.1 has to return. **That's the first item and
it's the important one.**

---

## 1. NEW: the traversal must distinguish "arrow-navigable" from "unreachable"

I nearly shipped a checker that would have failed our own gate.

Week 4's gate is *"injected trap detected, **zero false alarms on clean APG
widgets**"*. Here is the false alarm:

```
An APG tablist with 6 tabs exposes exactly ONE Tab stop.
The other 5 carry tabindex="-1" and are reached with ARROW keys.
That is correct authoring — it's the roving tabindex pattern.

A traversal that only presses Tab sees 5 elements it never landed on.
If it reports them as unreachable, I report an SC 2.1.1 failure
on a widget built exactly to spec.
```

So `UnreachedReason` now has a fifth value:

```python
class UnreachedReason(str, Enum):
    SHADOW_DOM      = "shadow-dom"       # our blind spot  -> cantTell
    IFRAME          = "iframe"           # our blind spot  -> cantTell
    UNKNOWN         = "unknown"          # our blind spot  -> cantTell
    NOT_FOCUSABLE   = "not-focusable"    # real barrier    -> FAIL
    OBSCURED        = "obscured"         # real barrier    -> FAIL
    ARROW_NAVIGABLE = "arrow-navigable"  # correct authoring -> ignored
```

**What you need to do:** when the traversal skips an element because it sits
inside a roving-tabindex widget, classify it `ARROW_NAVIGABLE`, not
`NOT_FOCUSABLE`. The patterns that do this are `tablist`, `menu`, `menubar`,
`radiogroup`, `tree`, `treegrid`, `grid`, `listbox` and `toolbar` — an element
with `tabindex="-1"` whose ancestor carries one of those roles.

If you classify them as `NOT_FOCUSABLE` we fail the gate on the first APG
example we test. If in doubt, `UNKNOWN` is safe — it produces `cantTell`
rather than a false failure.

There are two tests pinning this:
`test_arrow_navigable_tabs_are_not_reported_as_unreachable` and
`test_arrow_navigable_does_not_mask_a_real_barrier`.

> This is the whole argument for the plan's "artifact before runner code"
> rule, which we nearly skipped. Writing `data/apg-contracts/tablist.yaml`
> first is what surfaced it. Worth a minute at the pair session.

## 2. The contract is now in `verity-schema.json`

`export_schema.py` only exported `AuditReport` and `RenderArtifact`. Neither
references `RegionSample` or `TraversalResult`, so **your Week 3 sampling
payload was never in the shared contract file either** — nobody noticed. Both
are now exported explicitly.

Run `uv run python export_schema.py` after pulling. `TabStop`,
`TraversalResult`, `UnreachedRegion` and `RegionSample` will all be in there,
so you have the exact shape to build A4.1 against rather than reading my
Python.

If anything in the shape is awkward to produce from Playwright, tell me and
I'll change it — much better now than after you've built to it.

## 3. `data/apg-contracts/tablist.yaml` — my half of the shared artifact

Written by hand from the APG tabs pattern and ARIA 1.2, before the runner
code, per the plan. 8 structural assertions, 7 keyboard assertions, and — the
part I'd point you at — a `not_asserted` section listing what we deliberately
*don't* check and why.

**Write yours independently before reading mine if you still can.** The
comparison is the point of the ritual; where we differ is where we don't yet
agree on what "correct" means.

Two things in mine that will matter for A4.4's loader:

- Every assertion has `severity: violation | warning`. `warning` maps to
  `cantTell` / `NEEDS_REVIEW` and can never gate a build. Legitimate variants
  live here — e.g. arrow-key wrapping at the first/last tab is optional in the
  APG, so asserting either behaviour would be a false alarm.
- `not_asserted` is a real section, not commentary. It stops a future version
  quietly adding a check that a machine can't actually make.

## 4. Still outstanding from the previous list

- **A4.1** tab-order capture — still the blocker; nothing calls Tab yet
- **A4.2** multi-cycle trap detection, N by measurement, recorded in
  `docs/measurements/`
- **A4.3** focus-visible before/after diff — also unblocks B2.3, which has
  been unmeasurable since Week 2
- **A4.4** APG contract loader — `rulepacks/apg-contracts/` is still empty
- **Register the three new injectors** in `eval/corpus/build.py`
  (`keyboard_trap`, `positive_tabindex`, `outline_none` — allowed-attribute
  sets are in the previous doc)

---

## Joint — two ADRs are waiting on you

I've drafted the context for both. Decision, Consequences and Alternatives
are deliberately blank because they need agreeing, and both need your
signature.

- [`../adr/0003-the-model-localises-the-math-decides.md`](../adr/0003-the-model-localises-the-math-decides.md)
  — **overdue from Week 3.** Proposed decision: *a model may never produce a
  value that determines a verdict.* Models localise, classify and abstain;
  numbers that decide conformance come from deterministic computation over
  measured inputs.
- [`../adr/0004-keyboard-three-state-outcomes.md`](../adr/0004-keyboard-three-state-outcomes.md)
  — three-state outcomes, and the rule that a `fail` may be asserted from
  partial evidence but a `pass` may not.

Teach-back notes are scaffolded at
[`../teachback/2026-W03.md`](../teachback/2026-W03.md) and
[`../teachback/2026-W04.md`](../teachback/2026-W04.md). I've written my half
of W03 from reading your sampling code, including three things I couldn't
explain unaided — the glyph/background split rule is the main one. Your halves
are stubs. `2026-W01` is still missing entirely.

Pair session this week runs against the APG reference implementations. Every
one must produce zero findings; anything that doesn't is a design bug on my
side and I'll fix it this week, so send me whatever trips.
