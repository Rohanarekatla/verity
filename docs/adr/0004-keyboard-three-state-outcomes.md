# ADR-0004: Three-state keyboard outcomes, and what a pass has to earn

**Status:** DRAFT — context written by B, decision to be agreed and signed jointly.
**Date:** _pending_
**Signed:** Nikhil ____ / Rohan ____ (both must sign — see team-plan §2.6)
**Week:** 4 (7–13 Sep)

---

## Context

Week 4's gate is asymmetric in an unusual way:

> **injected trap detected, ZERO false alarms on clean APG widgets**

Detecting the broken thing is the easy half. The hard half is staying quiet on
widgets that are built correctly — and the plan is explicit that *every false
alarm on a correctly-built widget is a design bug and must be fixed this week*.

Correct widgets look wrong to a naive checker. The clearest case: an APG
tablist with six tabs deliberately exposes **one** Tab stop. The other five
carry `tabindex="-1"` and are reached with arrow keys. A checker that only
presses Tab sees five unreachable controls and reports an SC 2.1.1 failure on
a widget that is textbook-correct.

### Two rules emerged while building this

**1. Three states, not two.** `pass` / `fail` / `indeterminate`, where
`indeterminate` maps to `outcome=cantTell`, `provenance=NEEDS_REVIEW`, and
`confidence=0.0`. It never gates a build. This is not a polite word for
"fail" — it is the honest answer when the traversal did not gather enough
evidence to say either way, and keyboard traversal is flaky in a way pixel
sampling is not (transitions mid-flight, lazily hydrated widgets, focus
escaping to browser chrome).

**2. Evidence of a defect stands alone; absence of evidence needs complete
coverage.** Seeing a missing focus ring or a positive `tabindex` is a fact
about the page whether or not the traversal finished. Saying "this page
passes" is a claim about *every* stop, including the ones never reached, and
requires `complete=True`.

This second rule was not obvious. The first implementation of
`judge_focus_visible` got it backwards and reported SC 2.4.7 as **satisfied**
on a traversal that died halfway, based only on the handful of stops it
reached before timing out. A test caught it. Both halves are now pinned by
tests so the mistake cannot come back.

### What this cost us in recall, deliberately

- **SC 2.4.3** asserts exactly one thing: a positive authored `tabindex`. A tab
  order that differs from DOM order is *not* reported — CSS reordering,
  dialogs and roving tabindex all do it legitimately. "Meaningful order" is a
  human question and we do not attempt it.
- **SC 2.4.7** treats `focus_visible=None` ("not measured") as distinct from
  `False` ("measured, nothing there"). Collapsing them would fabricate a
  failure on every stop the screenshot diff happened to skip.
- **SC 2.1.1** distinguishes three kinds of `unreached`: a real barrier, our
  own blind spot (shadow DOM, iframes), and correct authoring
  (`ARROW_NAVIGABLE`). Only the first is a failure.

That last category was found by writing `data/apg-contracts/tablist.yaml`
before the runner code, which is exactly what the "artifact before code" rule
in the plan is for. Without it the checker would have failed the gate on the
first APG example we pointed it at.

### Retry policy (B4.4)

Re-run while anything is indeterminate, capped at 3 total attempts. Three
rules: bounded, never retry a settled decision, and **indeterminate is a
legitimate final answer** — running out of attempts does not escalate to
`fail` or downgrade to `pass`.

---

## Decision

> _To agree jointly. Proposed wording:_
>
> Interaction judgments are three-state. `indeterminate` is a first-class
> outcome, not a failure mode, and maps to `NEEDS_REVIEW` / `cantTell` /
> confidence 0.0.
>
> A `fail` may be asserted from partial evidence. A `pass` may not — it
> requires the traversal to report `complete=True`.
>
> Where a widget pattern legitimately produces behaviour that looks like a
> defect, the pattern is recorded as a contract in `data/apg-contracts/`
> **before** the checking code is written, and the checker is built to honour
> it.

---

## Consequences

> _To write jointly. Starting points:_
>
> - Track A's traversal must classify `unreached` honestly and specifically;
>   a single "couldn't reach it" bucket makes rule 2 unenforceable.
> - `complete=False` must be reported truthfully. A partial traversal that
>   claims completeness turns a truncated stop list into fabricated passes.
> - Every new widget pattern we support needs its contract written first.
> - Recall on SC 2.4.3 is intentionally low. Revisit only with evidence that
>   the extra findings would be true.

---

## Alternatives rejected

> _To write jointly._
>
> - **Two states, with indeterminate folded into fail.** Rejected: it fails
>   the gate on the first flaky run and trains users to ignore the tool.
> - **Two states, with indeterminate folded into pass.** Rejected: silently
>   converts "we didn't check" into "it's fine", which is the failure this
>   whole product is built to avoid.
> - **Infer roving tabindex heuristically rather than from a contract.**
>   Rejected: a heuristic that guesses which widgets are allowed to hide tab
>   stops will be wrong on the widgets nobody tested it against.
