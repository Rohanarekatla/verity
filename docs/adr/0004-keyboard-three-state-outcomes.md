# ADR-0004: Three-state keyboard outcomes, and what a pass has to earn

**Status:** PROPOSED — decision drafted by B, awaiting Rohan's agreement and both signatures.
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

Three rules.

**1. Interaction judgments are three-state.** `pass` / `fail` /
`indeterminate`, where `indeterminate` is a first-class outcome rather than a
failure mode. It maps to `outcome=cantTell`, `provenance=NEEDS_REVIEW`,
`confidence=0.0`, and never gates a build.

**2. Evidence of a defect stands alone; absence of evidence requires complete
coverage.** A `fail` may be asserted from a partial traversal — a missing
focus ring seen on a stop we visited is a fact regardless of whether we
finished. A `pass` may not: it is a claim about every stop on the page,
including the ones never reached, and requires `complete=True`.

**3. Widget patterns are contracted before they are checked.** Where a
pattern legitimately produces behaviour that looks like a defect, it is
written as a contract in `data/apg-contracts/` **before** the checking code,
and the checker is built to honour it.

Rule 3 is the one we nearly skipped. Writing `tablist.yaml` first is what
surfaced `ARROW_NAVIGABLE`; without it the checker would have reported five
unreachable tabs on the first APG reference implementation and failed the
gate on a widget built exactly to spec.

> _Rohan — B's proposed wording. Rule 3 in particular is a commitment about
> how we work, not just about this checker, so it needs a real yes from you
> rather than a nod._

---

## Consequences

- **Track A's traversal must classify `unreached` specifically.** A single
  "couldn't reach it" bucket makes rule 2 unenforceable, because a real
  barrier, our own blind spot and correct roving-tabindex authoring all
  become indistinguishable.
- **`complete=False` must be reported truthfully.** A partial traversal that
  claims completeness turns a truncated stop list into fabricated passes.
  This is not hypothetical — the first implementation of
  `judge_focus_visible` reported SC 2.4.7 as satisfied on a traversal that
  died halfway, and a test caught it.
- **Every new widget pattern costs a contract first.** Menu, radiogroup,
  tree, grid and listbox all use roving tabindex and will each need one
  before they can be checked. That is real, recurring work; rule 3 is not
  free.
- **Recall on SC 2.4.3 is intentionally low.** We assert exactly one thing —
  a positive authored `tabindex`. Revisit only with evidence that the extra
  findings would be true.
- **Retries cost wall-clock time in CI.** Capped at 3 attempts, so the worst
  case is bounded and predictable rather than unbounded.

---

## Alternatives rejected

- **Two states, indeterminate folded into `fail`.** Rejected: fails the gate
  on the first flaky run, and trains users to ignore the tool — which
  destroys the value of the findings that *are* real.
- **Two states, indeterminate folded into `pass`.** Rejected: silently
  converts "we didn't check" into "it's fine". This is the exact failure the
  product exists to avoid, and it is worse than the first option because it
  is invisible.
- **Infer roving tabindex heuristically instead of from a contract.**
  Rejected: a heuristic that guesses which widgets may legitimately hide tab
  stops will be wrong on the widgets nobody thought to test it against, and
  it will be wrong silently.
- **Assert a `pass` from partial coverage but mark it low-confidence.**
  Rejected: `cli.py` gates on provenance, not on confidence, so a
  low-confidence pass is operationally identical to a full one. Confidence is
  not a substitute for an honest outcome.
