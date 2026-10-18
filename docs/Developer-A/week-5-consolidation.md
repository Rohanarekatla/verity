# Week 5 — consolidation close-out (Track A)

Week 5 · 14–20 Sep · planned light week. ▶ Gate Sun 20 Sep: Phase 1 demoable
end-to-end from a clean checkout, all Phase 1 ADRs written, both pass the
bus-factor test.

Done late, during the Phase-2 catch-up — recording the real state rather than
pretending the gate was met on time (it was not; Week 4 and Week 5 both
slipped, see `blocking-track-b.md`).

---

## S5.1 — ADRs signed ✅

All three Phase-1 ADRs now carry a Decision and Rohan's signature:

- **ADR-0002** (vision descope) — Decision written against the real Spike A
  numbers: **descoped to an experiment, gated on a re-run**. The bar was not
  moved to fit the result; the result did not meet it, and that is recorded.
  *This is the one call worth a second look from Nikhil* — it sets product
  direction, not just an implementation detail.
- **ADR-0003** (model localises, math decides) — signed; Rohan's note records
  that A4.3 obeys rule 1 by construction, so the principle already generalised
  to the second checker.
- **ADR-0004** (three-state keyboard outcomes) — signed, including rule 3
  ("contract before checker") as a standing Phase-2 commitment.

> Nikhil authored the 0003/0004 Decisions as proposals and the 0002 Context;
> Rohan reviewed and agreed. If you (Nikhil) want to amend any wording now that
> they're ACCEPTED, that's a new ADR revision, not a silent edit — team-plan
> §2.6.

## S5.2 — README ✅ (Nikhil, during the break)

## S5.3 — test-coverage + CI green from a clean checkout — partial

The full suite passes locally with the worker built: **node 36/36, python
295/295** (unit) and the browser-integration tests green when `dist/` is
present. CI runs three jobs on `macos-latest` (node build+test, python pytest,
cross-language contract) and builds the worker in the contract job, so the
integration tests that the Python-only job skips actually run there.

**What is genuinely still open:** nobody has verified green *from a cold clone
on a machine that never built this repo* — which is what the gate asked for. A
fresh-checkout CI run (or a `git clone` into a clean container) is the missing
proof. Flagging it rather than claiming it.

## S5.4 — bus-factor test #1 — NOT done (needs a live session)

This one cannot be written; it has to be performed. The exercise: one of us
breaks a component the *other* owns, and the owner diagnoses it unaided inside
30 minutes, then we swap. The rotation handover (S5.5) is the precondition and
is now in place, so this is unblocked — it just needs a scheduled pair session.
It is deliberately left open rather than marked done.

## S5.5 — rotation #1: Static/DOM Agent A → B ✅ (note written)

`docs/handover/static-dom-agent.md` now exists — the component, its
non-obvious invariants, the two teach-back thin spots answered, and a suggested
first non-trivial commit (the fontSize/fontWeight addition ADR-0003 defers).
Nikhil owns the Static/DOM Agent from Phase 2; the Interaction Agent (A4.x)
stays with Rohan.

## Teach-backs

- **W02** — complete (both halves).
- **W03** — complete: Nikhil's A→B was already in; Rohan's B→A (worst-case
  ratio, the adjudication band, empty-set → None) now written.
- **W04** — Rohan's B→A (three-state outcomes, None-vs-False, ARROW_NAVIGABLE,
  retry policy) now written. Nikhil's A→B half (listening to the traversal) is
  his to write — the traversal has landed, so the code is now there to teach
  from.
- **W01** — still missing. Either backfill or accept the gap explicitly; it's
  the oldest lapsed ritual.

---

## Net

Phase-1 ADRs: done. Rotation note: done. Teach-backs: Rohan's halves done.
Still open and honest about it: the live bus-factor exercise (S5.4) and a true
cold-clone CI run (S5.3), plus W01's teach-back. None of those block Week 6
code, which is proceeding.
