# Rohan — Week 4 action items (Track A)

Week 4 · 7–13 Sep · keyboard traversal and trap detection.
▶ Gate Sun 13 Sep — **injected trap detected, zero false alarms on clean
APG widgets.**

Track B (B4.1–B4.4) is written and tested. Everything below is Track A, and
**item 1 is what the rest of the week hangs on** — none of my judgments can
run against a real page until the traversal exists.

---

## 1. A4.1 — Tab-order capture (the blocker)

I need a new RPC method. The current surface is `ping`, `render`, `runAxe`,
`sampleRegion`, `releaseArtifact` — there is nothing that presses Tab.

**I have already defined the return shape** in `verity/models/schemas.py`
(`TabStop`, `UnreachedRegion`, `TraversalResult`). Please build A4.1 to
produce exactly that, and tell me if anything in it is wrong or awkward to
produce — I would much rather change it now than have the two sides drift
like `element_screenshots` did in Week 2.

```python
class TraversalResult:
    stops: list[TabStop]          # every resting place of focus, in order
    cycles_requested: int
    cycles_completed: int
    returned_to_origin: bool
    trap_detected: bool           # A4.2 owns this verdict
    trap_selector: str | None
    unreached: list[UnreachedRegion]
    complete: bool                # did the traversal run to completion?
    incomplete_reason: str | None

class TabStop:
    order: int                    # position in the observed tab order
    selector: str
    cycle: int
    bbox: BoundingBox | None
    role: str | None
    accessible_name: str | None
    tabindex: int | None          # the AUTHORED attribute, not computed
    focus_visible: bool | None    # A4.3 fills this; None = not measured
    dom_order: int | None         # document order, for comparison
```

### Four things my code depends on being exactly right

**`tabindex` must be the authored attribute, not the computed one.** A
positive authored `tabindex` is the *only* SC 2.4.3 failure I assert. If you
send the computed value, every focusable element reports a number and I
cannot tell an authored `tabindex="99"` from a plain `<button>`. Send `None`
when the attribute is absent.

**`focus_visible` is three-valued and `None` is meaningful.** `None` means
"A4.3 did not measure this stop"; `False` means "measured, and there is no
indicator". If you send `False` for unmeasured stops I will report a focus
failure on every element your screenshot diff happened to skip — a
fabricated failure, and the gate says zero false alarms.

**`unreached` needs the reason, and the distinction matters.** I treat
`NOT_FOCUSABLE` and `OBSCURED` as real SC 2.1.1 failures — the user genuinely
cannot get there. I treat `SHADOW_DOM` and `IFRAME` as *our* blind spot and
downgrade the whole judgment to needs-review, because blaming a site for our
own traversal limitation is a false positive. Please don't collapse them.

**`complete: false` must be honest.** A traversal that timed out, lost focus
to browser chrome, or hit an unhandled shadow root observed *part* of the
page. I turn `complete=false` into `indeterminate` across the board. If a
partial traversal reports `complete=true` I will read a truncated stop list
as the whole page and invent failures.

## 2. A4.2 — Multi-cycle trap detection

You own the verdict; I read `trap_detected` and do not second-guess it.

The plan says assert only after N full cycles with **N determined by
measurement**, recorded in `docs/measurements/`. Please also set
`cycles_completed` honestly — I deliberately return `indeterminate` rather
than `pass` when `cycles_completed < cycles_requested`, because a trap that
first manifests on cycle 3 is invisible to a 2-cycle run, and "we didn't find
one" is not the same as "there isn't one".

## 3. A4.3 — Focus-visible before/after diff

This also closes a Week 2 gap: B2.3's focus-visible vision judgment has never
been measurable because nothing captures a focused screenshot. Once this
lands, that judgment can finally be evaluated (see ADR-0002, constraint 1).

For my part I only need the boolean per `TabStop`. Send `None` rather than
guessing.

## 4. A4.4 — `rulepacks/apg-contracts/` schema + loader

`rulepacks/apg-contracts/` and `data/apg-contracts/` are both still empty
except for READMEs.

## 5. Register the three new injectors in the corpus

Same job you did in A3.5 for `contrast_over_image`. I shipped three new ones
in `eval/inject/`, and without registration the corpus generates zero cases
for them, so the gate has nothing to measure:

| Injector | Breaks | Allowed attrs for `_ALLOWED_ATTRS` |
|---|---|---|
| `keyboard_trap` | SC 2.1.2 | `{"onkeydown", "tabindex", "data-verity-original-onkeydown-trap", "data-verity-added-tabindex-trap"}` |
| `positive_tabindex` | SC 2.4.3 | `{"tabindex", "data-verity-original-tabindex-pos"}` |
| `outline_none` | SC 2.4.7 | `{"style", "data-verity-original-style-outline"}` |

Note each uses a **distinct** marker attribute. `reduce_contrast`,
`contrast_over_image` and `outline_none` all write to `style`, so a shared
marker would let one injector's `revert` silently undo another's — a corpus
case that quietly lost its defect. There's a test asserting they can't
interfere (`test_style_writing_injectors_use_distinct_markers`).

Target selectors: `keyboard_trap` and `positive_tabindex` want focusable
elements (`a[href]`, `button`, `input`, `select`, `textarea`, `[tabindex]`);
`outline_none` wants the same.

---

## What Track B built this week

`verity/agents/keyboard.py` — one `TraversalResult` in, four findings out:

| SC | Judgment | Fails when |
|---|---|---|
| 2.1.1 Keyboard | `judge_keyboard_operable` | something focusable is genuinely unreachable |
| 2.1.2 No Keyboard Trap | `judge_no_keyboard_trap` | you set `trap_detected` |
| 2.4.3 Focus Order | `judge_focus_order` | a positive authored `tabindex` |
| 2.4.7 Focus Visible | `judge_focus_visible` | `focus_visible is False` on any stop |

Plus B4.2's three-state outcome (`pass` / `fail` / `indeterminate`, where
indeterminate → `cantTell` + `NEEDS_REVIEW` + confidence 0.0, which never
gates a build) and B4.4's retry policy — re-run while anything is
indeterminate, capped at 3 attempts, never escalating to `fail` just because
the attempts ran out.

**On the zero-false-alarms gate.** The judgments are deliberately narrow.
Focus order that differs from DOM order is *not* reported — CSS reordering,
dialogs and roving tabindex all do it legitimately. A tablist with roving
tabindex exposing one stop for six tabs passes cleanly; there's a test for
exactly that case. If you find any clean APG widget that trips a judgment,
send it to me — per the plan that's a design bug on my side and I'll fix it
this week.

**Not yet wired into `scan_url()`.** There's no method to call, so wiring it
now would be dead code. The moment `traverseTabOrder` (or whatever you name
it) exists, I'll wire it behind the same graceful-fallback guard the contrast
adjudicator uses.

---

## Joint, this week

- **Artifact (both):** the tablist APG contract as YAML, **by hand, before
  any runner code**. Write yours independently; we compare. Neither of us has
  done this yet and the plan is explicit about the ordering.
- **Pair (2 hrs):** run against APG reference implementations. *Every false
  alarm on a correctly-built widget is a design bug and must be fixed this
  week.*
- **ADR-0004.** Also ADR-0003 from last week is still unwritten.
- **Teach-back:** `docs/teachback/2026-W04.md`. `2026-W01` and `2026-W03`
  are both still missing.

---

Previous: [`week-3-action-items.md`](week-3-action-items.md)
