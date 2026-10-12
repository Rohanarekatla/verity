# State of play

**Last updated 22 Sep 2026**, during the 21–27 Sep break, after working ahead
into Week 6.

The execution plan asks for this note before the break, on the grounds that
*"neither engineer will reliably recall this in October."* That is its only
job: if you are reading it cold, this is where things actually stand — not
where they were meant to be.

---

## One-paragraph summary

Phase 1 shipped a working polyglot scanner: a real page goes in, Chromium
renders it, axe-core runs, and a strictly-typed `AuditReport` comes out with a
non-zero exit code when there is an authoritative failure. Two of three
planned wedges landed. Contrast-over-image adjudication works end to end.
Vision was **descoped to an experiment** after Spike A measured honestly and
the model abstained on 79% of cases. **Keyboard is half built** — the Python
judgments exist and are tested, but the browser-side traversal was never
written, so nothing calls them. Track B has also worked ahead into Week 6.
**Track A is one full week behind**, and that is the single thing gating
everything else.

**197 tests passing.** Never yet verified from a clean checkout.

---

## Where each week landed

| Week | Scope | Gate | Outcome |
|---|---|---|---|
| 1 · 10–16 Aug | Polyglot skeleton | Sun 16 Aug | **Met** |
| 2 · 17–23 Aug | ⚠ Spike A, vision precision | Sun 23 Aug | **Answered, not passed** — model abstained on 79% of 48 cases, zero false positives, near-zero recall |
| 3 · 31 Aug – 6 Sep | Contrast-over-image adjudication | Sun 6 Sep | **Met** |
| 4 · 7–13 Sep | Keyboard traversal + traps | Sun 13 Sep | **Missed** — Track B complete, Track A never started |
| 5 · 14–20 Sep | Consolidation | Sun 20 Sep | **Missed** — mostly skipped |
| 6 · 28 Sep – 4 Oct | Finding model, provenance, dedup | Sun 4 Oct | **Track B 3 of 4 done early** |

---

## What Track B (Nikhil) has done

### Week 1 — the pipe

| # | What |
|---|---|
| B1.1 | `models/schemas.py` — full Pydantic set, `Provenance` required with no default |
| B1.2 | `orchestrator/rpc_client.py` — long-lived subprocess, correlate by id, per-call timeout |
| B1.3 | `orchestrator/main.py` — render → runAxe → `Finding` |
| B1.4 | `cli.py` — `verity scan <url>`, non-zero exit on authoritative findings |
| B1.5 | `eval/inject/` — `strip_alt`, `detach_label`, `reduce_contrast`, all reversible |

### Week 2 — the vision spike

| # | What |
|---|---|
| B2.1 | Measured on real hardware → `docs/measurements/spike-a.md`. **Deviation recorded openly:** ran Qwen2.5-VL-7B-4bit, not the specified 8B build |
| B2.2 | `AltTextJudgment` + `ALT_TEXT_RUBRIC` |
| B2.3 | `FocusVisibleJudgment` + `FOCUS_VISIBLE_RUBRIC` — **written, never measurable** |
| B2.4 | `ContrastRegionLocalisation` — boxes only, never a ratio. **No labelled set built** |
| B2.5 | End-to-end latency recorded into `AuditReport.latency` |

### Week 3 — contrast adjudication

| # | What |
|---|---|
| B3.1 | `worst_case_ratio()` — minimum across the background sample set, not the average |
| B3.2 | `adjudicate_contrast()` wired into `scan_url()`. **No model in this path** |
| B3.3 | Four refusal branches, each with a reason code |
| B3.4 | `contrast_over_image` injector |

### Week 4 — keyboard

| # | What |
|---|---|
| B4.1 | `agents/keyboard.py` — maps a traversal to SC 2.1.1 / 2.1.2 / 2.4.3 / 2.4.7 |
| B4.2 | Three-state outcome; `indeterminate` → `cantTell` + `NEEDS_REVIEW` + confidence 0.0 |
| B4.3 | `keyboard_trap`, `positive_tabindex`, `outline_none` injectors |
| B4.4 | Retry policy, capped at 3 attempts |
| — | `TabStop` / `TraversalResult` / `UnreachedRegion` contract defined and exported |

### Week 5 — consolidation (shared week, partially covered)

- **S5.2** README brought up to reality (was four weeks stale)
- ADRs 0003 and 0004 written from blank drafts into proposed decisions
- Teach-back `2026-W03` (B's half) and `2026-W04` scaffolded
- `data/apg-contracts/tablist.yaml` — the required artifact, hand-written
- `export_schema.py` fixed: `RegionSample` and `TraversalResult` were missing
  from the shared contract file entirely

### Week 6 — worked ahead

| # | What |
|---|---|
| B6.2 | **Provenance enforced at construction.** A `model_validator` makes an incoherent `Finding` unconstructable — `AUTHORITATIVE` + `cantTell` now raises |
| B6.3 | `validator/severity.py` — severity as a policy, not an axe passthrough |
| B6.4 | Validator versioned (`VALIDATOR_VERSION`), proven browser-free by test |
| B6.1 | **Not started — depends on A6.1 + A6.2** |

---

## Pending on Track B

Short list, and none of it is blocked on effort:

1. **Wire `keyboard.py` into `scan_url()`** — about 10 lines. Blocked on A4.1.
2. **B6.1 dedup rule** — needs A6.1 (selector normalisation) and A6.2 (region
   identification). Will be a MAJOR validator version bump because it
   invalidates every waiver signature.
3. **Verify CI green from a clean checkout** — S5.3's actual ask. 197 tests
   pass locally; nobody has ever run them from a fresh clone.
4. **Receive the Static/DOM Agent rotation** and push one non-trivial commit
   to it. Blocked on Rohan's handover note.

One thing to decide rather than do: the **strongest-provenance-wins**
tie-break in dedup does *not* depend on Rohan. Today's first-wins rule is
enforced only by a comment about caller ordering, which is fragile. It was
left alone deliberately; worth a decision.

---

## What Rohan needs to pay attention to

Ordered by what unblocks the most.

### 1. A4.1 — tab-order capture (the blocker)

The RPC surface is `ping`, `render`, `runAxe`, `sampleRegion`,
`releaseArtifact`. **Nothing presses Tab.** `node-worker/interaction/` holds
only a README.

The return shape is already defined and exported — run
`uv run python export_schema.py` and build against `TraversalResult`.

**Four things the payload must get exactly right**, each with the false
positive it would otherwise cause:

| Field | Requirement | If wrong |
|---|---|---|
| `tabindex` | The **authored** attribute, `None` when absent — not the computed value | Every focusable element reports a number; SC 2.4.3 becomes unusable |
| `focus_visible` | Three-valued. `None` = not measured, `False` = measured and absent | A focus failure reported on every stop A4.3 skipped |
| `unreached[].reason` | Distinguish real barrier / our blind spot / `ARROW_NAVIGABLE` | See below — this one fails the gate |
| `complete` | Honest. `False` when the traversal didn't finish | A truncated stop list read as the whole page → fabricated passes |

### 2. `ARROW_NAVIGABLE` — the one that fails the gate

A correct APG tablist with six tabs exposes **one** Tab stop. The other five
carry `tabindex="-1"` and are reached with arrow keys. That is the roving
tabindex pattern and it is textbook-correct authoring.

A traversal that only presses Tab sees five elements it never landed on. If
those are classified `NOT_FOCUSABLE`, Track B reports an SC 2.1.1 failure on a
widget built exactly to spec — and Week 4's gate is *zero false alarms on
clean APG widgets*.

Patterns affected: `tablist`, `menu`, `menubar`, `radiogroup`, `tree`,
`treegrid`, `grid`, `listbox`, `toolbar`. If unsure, use `UNKNOWN` — it
produces `cantTell` rather than a false failure.

### 3. The rest of Week 4

- **A4.2** multi-cycle trap detection, N determined by measurement, recorded
  in `docs/measurements/`
- **A4.3** focus-visible before/after diff — also unblocks B2.3, unmeasurable
  since Week 2
- **A4.4** APG contract loader — `rulepacks/apg-contracts/` does not exist
- Register `keyboard_trap`, `positive_tabindex`, `outline_none` in
  `eval/corpus/build.py`

### 4. Week 5 items that need him

- **Sign ADRs 0002, 0003, 0004** — team-plan §2.6: not ready until both agree
- **S5.4 bus-factor test** — he breaks a Track B component, B diagnoses
  unaided in 30 min, then reverse
- **S5.5 rotation** — hand the Static/DOM Agent to B with a note in
  `docs/handover/`, which does not exist

### 5. Week 6, if it starts on time

- **A6.1** selector normalisation, stable across class-name churn
- **A6.2** region identification for findings without a clean selector
- **A6.3** regenerate the TS mirror from JSON Schema + **CI check that fails
  on drift** — this is the fix for the `element_screenshots` class of bug that
  went unnoticed for two weeks

---

## What is left after Rohan finishes

Assuming A4.x and A6.x land, this is the remaining work — and most of it is
small, because it was written in advance against a defined contract.

**Immediately unblocked, Track B:**

1. Wire `keyboard.py` into `scan_url()` (~10 lines)
2. **Measure B2.3 focus-visible** for the first time — it has a schema, a
   rubric and a judge, and has never seen data
3. Build the **B2.4 labelled localisation set** — the harness supports it
4. Implement **B6.1** dedup by (SC, normalised selector, region) with
   strongest-provenance tie-breaking

**Then the honest reckoning on two decisions:**

5. **Re-run Spike A, or accept the descope.** The current result is from a
   7B-4bit stand-in, not the specified 8B build, and `spike-a.md` names three
   possible causes for the 79% abstention that were never separated: rubric
   imbalance, model size, or the task simply being wrong for a VLM. If the
   cause is the rubric, "vision doesn't work" is the wrong conclusion to carry
   into Phase 2.
6. **Week 4's gate has still never been run.** Injected trap detected, zero
   false alarms on clean APG widgets — that needs the pair session against
   APG reference implementations. Any clean widget that trips a judgment is a
   design bug on Track B's side, to be fixed that week.

**And the rituals, which are genuinely behind:**

7. Sign three ADRs; run the bus-factor test; do the rotation
8. Teach-back `2026-W01` never existed; W03 and W04 each have one half
9. Verify CI green from a clean checkout

**Then Week 7 (waivers and baseline diffing) can start clean** — and it needs
B6.1 settled first, because a waiver written against the old signature scheme
stops matching the moment the dedup key changes.

---

## The three ideas to reload before touching anything

**1. A wrong finding is worse than a missing one.** A missed issue leaves the
user where they started. A false one costs them time, then trust, then the
tool — and the correct findings get ignored by association.

**2. Provenance has to be exactly true.** `authoritative` may gate a build;
`ai_assisted` annotates; `needs_review` reports. As of B6.2 this is enforced
at construction — an incoherent finding cannot be built.

**3. The model localises; the maths decides.** No schema handed to a model
contains a ratio, a score, or a pass/fail field.

Corollary from Week 4: **evidence of a defect stands alone; absence of
evidence requires complete coverage.** A `fail` can be asserted from a partial
traversal. A `pass` cannot.

---

## Landmines

- **`hash()` is salted per process.** Ids built on it changed every run.
  Everything identity-shaped uses `sha256`.
- **Injectors sharing a marker attribute silently undo each other.** Three
  write to `style`; each has its own marker.
- **`element_screenshots` drifted between TS and Python for two weeks** and
  nothing caught it. `RegionSample` and `TraversalResult` were missing from
  `verity-schema.json` entirely until 8 Sep for the same reason. A6.3's drift
  check is the real fix.
- **A stale `node-worker/dist/`** presents as `unknown method: sampleRegion`,
  which looks like a Python bug. Run `npm run build` first.
- **Roving tabindex looks like a keyboard failure.** Found by writing the APG
  contract *before* the runner code — which the plan required and we nearly
  skipped.
- **`git status` shows ~95 modified files** that nobody touched. That is a
  CRLF artifact of the OneDrive mount. Use
  `git diff --ignore-all-space --stat` for the truth, and stage paths
  explicitly rather than `git add .`.

---

## Schedule reality

Phase 2 starts **28 Sep**. Week 6 assumes a Phase 1 signed off at the 20 Sep
gate; it wasn't.

Two options, and this is a joint call:

**(a) Finish Week 4 first.** A4.x lands in the opening days of Phase 2, then
the bus-factor test and rotation, then Week 6 a few days late.

**(b) Start Week 6 on time and let keyboard slip** to the Week 9 buffer,
trimming the Bible's claims to match — the *knowingly* option, same posture as
the Spike A descope.

What to avoid is starting Week 6 while telling ourselves Week 4 is nearly
done. It isn't.

Also worth ten minutes: **dedup and waivers landed early**, back in Week 2. So
B6.1 and B7.1–B7.2 are partly built. Week 6/7 should probably review and
harden them rather than re-specify them.
