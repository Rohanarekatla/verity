# Rohan — before Week 6 starts (28 Sep)

We're in the scheduled break, 21–27 Sep. Six days until Phase 2.

I've used it to write the state-of-play note the plan asks for
([`../status.md`](../status.md)), bring the README up to reality, and turn
ADRs 0003 and 0004 into proposed decisions rather than empty drafts.

This is what's outstanding on your side, and one thing we have to decide
together before Week 6 can sensibly start.

---

## 1. Week 4 Track A never landed

The RPC surface is still `ping`, `render`, `runAxe`, `sampleRegion`,
`releaseArtifact`. `node-worker/interaction/` has only a README and
`rulepacks/apg-contracts/` doesn't exist.

- **A4.1** tab-order capture
- **A4.2** multi-cycle trap detection, N by measurement
- **A4.3** focus-visible before/after diff
- **A4.4** APG contract schema + loader
- Register `keyboard_trap`, `positive_tabindex`, `outline_none` in
  `eval/corpus/build.py`

Full detail, including the four things the payload has to get exactly right,
is in [`week-4-followup-for-rohan.md`](week-4-followup-for-rohan.md). The
contract is now in `verity-schema.json` — run
`uv run python export_schema.py` after pulling and you'll see `TabStop`,
`TraversalResult` and `UnreachedRegion` in there.

**The consequence, stated plainly:** Track B's keyboard judgments are written
and tested but have never seen a real page, because there's nothing to call.
That's half a wedge, and the Week 4 gate (13 Sep) went unmet.

## 2. Week 5 consolidation — three items need you

| # | Task | Why it needs you |
|---|---|---|
| S5.1 | Sign ADRs 0002, 0003, 0004 | team-plan §2.6 — an ADR isn't ready until both agree |
| S5.4 | Bus-factor test #1 | You break a Track B component, I diagnose unaided in 30 min, then reverse |
| S5.5 | Rotation #1: Static/DOM Agent A → B | You write the handover note; `docs/handover/` doesn't exist yet |

S5.5 is the one I'd flag. Rotation means I take ownership of the Static/DOM
Agent and you don't touch it for Phase 2. I can't start that without your
handover note, and the plan expects me to push a non-trivial commit to it —
so the sooner it exists, the less it stalls me.

I did S5.2 (README) and made a start on S5.3 — there are 166 test functions,
but **nobody has ever verified CI green from a clean checkout**, which is what
the gate actually asked for.

## 3. Two ADRs waiting on you

Both now have a real Decision section rather than a blank one. Argue with
them — that's more useful than agreeing.

- [**ADR-0003**](../adr/0003-the-model-localises-the-math-decides.md) — *a
  model may never produce a value that determines a verdict.* Three testable
  rules. The cost is stated honestly: the 3.0–4.5 contrast band stays
  `cantTell` rather than being resolved by a model guessing at font size.
- [**ADR-0004**](../adr/0004-keyboard-three-state-outcomes.md) — three-state
  outcomes, and *evidence of a defect stands alone; absence of evidence
  requires complete coverage.*

**Rule 3 in ADR-0004 is the one to read properly.** It commits us to writing
a widget contract *before* the checking code, for every pattern. That's
recurring work — menu, radiogroup, tree, grid and listbox all use roving
tabindex and will each need one. I've said so in the Consequences rather than
pretending it's free. If you think that's too expensive, say so now; it's a
commitment about how we work, not just about this checker.

---

## 4. The thing we have to decide together

**Week 6 assumes a Phase 1 that was signed off at the 20 Sep gate.** It
wasn't — Week 4 is half done and Week 5 was skipped. Two options, and this is
a joint call:

**(a) Finish Week 4 first.** A4.x lands in the opening days of Phase 2, we do
the bus-factor test and rotation, then start Week 6 a few days late. Phase 2
has a lighter week later that could absorb it.

**(b) Start Week 6 on time and let keyboard slip.** Keyboard moves to the
Week 9 buffer, and we trim the Bible's claims to match. This is the
*knowingly* option — same posture as the Spike A descope.

What I'd argue against is starting Week 6 while telling ourselves Week 4 is
nearly done. It isn't, and the whole point of the rituals is that we notice
that now rather than in October.

**One more thing worth deciding at the same time:** dedup and waivers landed
early, back in Week 2. So B6.1 and B7.1–B7.2 are already partly built. Week 6
should probably *review and harden* them rather than re-specify them — but
that's worth ten minutes of agreement rather than both of us assuming
different things.

---

Everything above is recorded in [`../status.md`](../status.md) too, so neither
of us has to reconstruct it from memory after the break.
