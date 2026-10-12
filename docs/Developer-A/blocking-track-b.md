# Rohan — what's blocking Track B

**Written 12 Oct 2026, covering Weeks 4–8.** This is the single consolidated
blocker list; it supersedes the per-week notes linked at the bottom.

Not a status report — a dependency list. Each item below has Track B work
sitting finished and unable to run until it lands.

---

## The situation, stated plainly

Your last commit is **`d73cfd0`, 5 September** (A3.5, registering the
`contrast_over_image` injector). I checked `origin/Rohan`, `origin/main` and
`origin/Nikhil` — there is nothing newer from Track A on any branch.

That is **Weeks 4, 5, 6 and 7 with no Track A work**. Four missed gates:

| Gate | Date | Needed from Track A | Landed |
|---|---|---|---|
| Keyboard trap detection | Sun 13 Sep | A4.1–A4.4 | No |
| Phase 1 demoable, ADRs signed | Sun 20 Sep | S5.4, S5.5, signatures | No |
| No finding without explicit provenance | Sun 4 Oct | A6.1–A6.3 | No |
| One new defect fails the build, not 50 old ones | Sun 11 Oct | A7.1, A7.2 | No |

I'm not raising this to assign blame — I'm raising it because Track B has
worked ahead to Week 7 and is now **blocked in five separate places**, and
the plan's rituals exist precisely so this gets noticed now rather than in
December.

---

## What is blocked, and by what

### 1. A4.1 tab-order capture → blocks the entire keyboard wedge

`verity/agents/keyboard.py` is written and has 30 passing tests. It has
**never seen a real page**, because no RPC method presses Tab. The surface is
still `ping`, `render`, `runAxe`, `sampleRegion`, `releaseArtifact`.

Wiring it in is about ten lines on my side. Until A4.1 exists there is
nothing to call.

The return shape is already defined and exported — `uv run python
export_schema.py` and build against `TraversalResult`. Four fields have to be
exactly right; each one has a specific false positive attached if it isn't:

| Field | Requirement | If wrong |
|---|---|---|
| `tabindex` | The **authored** attribute, `None` when absent | Every focusable element reports a number; SC 2.4.3 becomes unusable |
| `focus_visible` | Three-valued: `None` = not measured, `False` = measured and absent | A focus failure on every stop A4.3 skipped |
| `unreached[].reason` | Distinguish real barrier / blind spot / `ARROW_NAVIGABLE` | **Fails the gate** — see below |
| `complete` | Honest `False` when the traversal didn't finish | Truncated stop list read as the whole page → fabricated passes |

**`ARROW_NAVIGABLE` is the one to read twice.** A correct APG tablist with six
tabs exposes **one** Tab stop; the other five carry `tabindex="-1"` and are
reached with arrow keys. If you classify those as `NOT_FOCUSABLE`, Track B
reports an SC 2.1.1 failure on a widget built exactly to spec — and Week 4's
gate is *zero false alarms on clean APG widgets*. Affected patterns:
`tablist`, `menu`, `menubar`, `radiogroup`, `tree`, `treegrid`, `grid`,
`listbox`, `toolbar`. If unsure, `UNKNOWN` is safe — it yields `cantTell`
rather than a false failure.

### 2. A4.3 focus-visible diff → blocks B2.3, unmeasured since Week 2

`FocusVisibleJudgment` has a schema, a rubric and a judge. It has never been
evaluated against data, because nothing captures a focused screenshot. This is
the oldest outstanding blocker in the project.

### 3. A6.1 + A6.2 → block B6.1, the dedup key

The plan calls for dedup by **(SC, normalised selector, region)** with
strongest-provenance tie-breaking. Today's key is
`(SC, selector, rule_id)` with first-wins.

I cannot change it: "normalised selector" is A6.1 and "region" is A6.2.
Neither exists, so there is nothing to key on. The validator version comment
records that this will be a MAJOR bump when it lands, because it invalidates
every waiver signature.

### 4. A7.1 stable `finding_signature` → affects waivers I just shipped

I built Week 7's waiver machinery this week (B7.1–B7.3). It keys on the
current signature, which is **not** yet stable against a formatter or a
class-name hasher — that is A7.1.

So: waivers work, are schema-enforced and expire properly, but a team that
runs Prettier over their templates may find their waivers stop matching.
Worth doing A7.1 before anyone writes real waivers, rather than after.

### 5. A7.2 baseline storage → blocks B7.4

B7.4 is "diff/regression keyed to `ruleset_version` + corpus hash". The
keying is mine; the content-addressed baseline store is A7.2. Not started, so
B7.4 is the one Week 7 task I left alone.

---

## Week 8 — Track B is done; the gate still needs you

I built B8.1–B8.4 this week: SARIF 2.1.0 output, `partialFingerprints`, JUnit
XML, and the configurable `ci: { fail_on, annotate_on }` policy. Plus the
shared artifact, hand-written before the generator per the plan:
[`../sarif-reference.md`](../sarif-reference.md).

Yours:

| # | Task |
|---|---|
| A8.1 | `action/` — GitHub Action wrapping the CLI |
| A8.2 | Action caches model + browser binaries between runs |
| A8.3 | Baseline-commit workflow — proposes a baseline update in a PR, never automatic |

Week 8's gate is *PR annotations appear inline; build fails only on new
authoritative findings*. **It is unreachable without A8.1** — there is no
Action, so there is nothing to annotate from, and nothing to upload the SARIF
I now generate. The plan calls this "the first useful thing" and suggests a
soft public release at the end of it.

### A decision for the pair session, surfaced by doing the artifact first

**Verity scans a URL. SARIF annotates a file.**

An inline PR annotation needs `artifactLocation.uri` plus `region.startLine`
— a repo-relative path and a line number. A finding on
`https://staging.example.com/pricing` has neither, and a DOM selector is not
a file position. So the generator handles three cases honestly rather than
guessing:

| Scanned | Inline annotation? |
|---|---|
| A local file inside the repo | **Yes** — URL mapped to the relative path |
| A dev-server URL with a source map the user supplies | Not in scope this week |
| An arbitrary remote URL | **No** — emitted with no `physicalLocation`; Security tab only, page URL in the message |

I deliberately do **not** invent a path when there isn't one: a wrong `uri`
uploads successfully and then annotates the wrong line of the wrong file,
which is worse than no annotation.

**This shapes A8.1 directly.** Whether the Action scans built files from the
checkout (annotatable) or a deployed preview URL (not annotatable) changes
what the headline feature of Week 8 actually *is*. My read: default to local
built files precisely so annotations work, and treat remote-URL scanning as a
separate mode that reports to the Security tab. But that's a joint call.
Full reasoning in [`../sarif-reference.md`](../sarif-reference.md) §5.

### And one more reason A7.1 matters

`partialFingerprints` is how GitHub tells "same alert" from "new alert"
across commits. Mine is keyed on the dedup signature, which is **not yet
stable against a code formatter or a class-name hasher** — that's A7.1. Until
it lands, running Prettier over a template can make every alert look new.

I versioned the key (`verityFindingSignature/v1`) so the scheme can change
later without GitHub silently merging two incompatible fingerprints. But it's
cheaper to fix the signature before anyone's alert history depends on it.

### What I could not verify

Confirming the SARIF renders as an inline annotation needs a PR against a
repo with code scanning enabled. A current sample is regenerated at
`eval/fixtures/minimal.sarif.json` on every test run, demonstrating all three
levels. The upload command is in
[`../sarif-reference.md`](../sarif-reference.md) §6.

---

## Also still open from Week 5

Non-technical, roughly an hour total:

- **Sign ADRs 0002, 0003, 0004.** 0003 and 0004 now have real Decision
  sections written as proposals — argue with them rather than rubber-stamping.
  team-plan §2.6: an ADR isn't ready until both agree.
- **S5.4 bus-factor test** — you break a Track B component, I diagnose it
  unaided in 30 minutes, then reverse.
- **S5.5 rotation** — hand the Static/DOM Agent over with a note in
  `docs/handover/`, which does not exist. I'm meant to own it for Phase 2 and
  push a non-trivial commit to it; I can't start without the handover.
- **Teach-back `2026-W01`** was never written; W03 and W04 have one half each.

---

## What I'd suggest, in priority order

1. **A4.1 + A4.3.** Unblocks the keyboard wedge *and* B2.3. Biggest single win.
2. **A8.1.** Week 8's gate is impossible without it, and it's the surface a
   stranger judges the project by.
3. **A7.1.** Cheap now, expensive once real waivers exist.
4. **A6.1 + A6.2.** Unblocks B6.1.
5. **The Week 5 hour** — signatures, bus-factor, rotation note.

If that's more than this week holds, say so and we re-plan the schedule
together rather than letting four more gates slip. The *knowingly* posture we
took on the Spike A descope applies here too: deciding to drop keyboard to the
Week 9 buffer is fine. Discovering in December that it never shipped is not.

Full picture: [`../status.md`](../status.md).
Previous lists: [`week-4-followup-for-rohan.md`](week-4-followup-for-rohan.md),
[`before-week-6.md`](before-week-6.md).
