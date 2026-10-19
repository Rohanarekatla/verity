# Handover — Confidence & calibration (Nikhil → Rohan)

**Rotation #2 (end of Phase 2, Week 9).** From Phase 3 Rohan owns confidence
and calibration and I step back from it (team-plan §2.4). The execution plan
already writes Week 12 as "A *(owns calibration since rotation #2)*" — A12.1
isotonic, A12.2 conformal, A12.3 three-bucket presentation, A12.4 drift — so
this note is what you need to start there without archaeology.

The one-line version: **today nothing is calibrated, and that is on purpose.**
Every confidence in the system is either 1.0 (a deterministic verdict) or 0.0
(undecided), and the type system refuses anything in between that is not
labelled as model output. Calibration is the work of making the in-between
values mean something before any of them is allowed near a user.

---

## What exists

| Concern | Where | Task |
|---|---|---|
| `Confidence {score, method, model, escape_used}` | `verity/models/schemas.py` | B1.x |
| Provenance enforced at construction (`_provenance_is_coherent`) + `revalidate()` | `verity/models/schemas.py` | B6.2 |
| Severity policy: undecided / non-authoritative capped at MODERATE | `verity/agents/validator/severity.py` | B6.3 |
| Contrast: incomplete → 0.0 `axe-incomplete`; adjudicated → 1.0 `wcag-contrast-arithmetic`; inconclusive → 0.0 `contrast-inconclusive` | `verity/agents/contrast.py` | B3.x |
| Keyboard three-state (pass / fail / cantTell) | `verity/agents/keyboard.py`, ADR-0004 | B4.2 |
| APG contracts: decided → 1.0 `apg-contract`; else 0.0 `apg-contract-indeterminate` | `verity/agents/interaction.py` `to_findings` | A9.1 |
| Only AUTHORITATIVE gates (default `fail_on`) | `verity/report/policy.py` | B8.4 |
| The model layer that will produce in-between scores | `verity/agents/vision.py`, `vision_backends.py`, ADR-0002/0003 | Phase 3 |
| `verity/calibration/` | README only — **empty, yours** | A12.1–A12.4 |

Tests that pin it: `verity/tests/test_provenance.py` (the invariant itself,
including a grep for every `Finding(` construction site),
`test_severity.py`, `test_contrast*.py`, `test_keyboard*.py`.

---

## The invariants (break these and it fails silently)

1. **AUTHORITATIVE ⇒ outcome decided, score 1.0, no model.** Enforced in the
   model validator. A finding a model touched is AI_ASSISTED by definition
   and must name the model (`confidence.model`), so you can tell which
   findings to re-run when the model changes.
2. **NEEDS_REVIEW ⇒ `cantTell`, score < 1.0.** "Undecided with full
   confidence" was a real shipped bug (Week 2); it is now unconstructable.
3. **The validator runs at construction, not assignment.** The pipeline
   builds an authoritative finding then downgrades it (`flag_needs_review`,
   `adjudicate_contrast`). Anything that mutates a finding must end coherent —
   call `finding.revalidate()` after a mutation path you add.
4. **`method` is the audit trail, not decoration.** Each code path that sets
   a score has its own method string. A calibration curve fitted per method
   is the natural key; do not collapse them.
5. **No numeric confidence in user-facing output** (A12.3). SARIF/JUnit
   today map provenance to level (error / warning / note) and never print
   the score — keep it that way.
6. **A pass needs complete coverage; a defect stands alone** (ADR-0004).
   Calibration must not turn "we looked at 60% of it" into a 0.6 pass.

---

## Where calibration plugs in

The natural seam is between a model's raw output and the `Confidence` it
produces in `vision.py`: raw score → (isotonic, per method, versioned by
ruleset) → calibrated probability → (conformal) singleton set? stays
AI_ASSISTED : becomes NEEDS_REVIEW. Nothing downstream needs to change,
because gating already keys on provenance, not score.

Things I would check first:

- **The held-out split (B12.1, mine) must exist before you fit anything.**
  Fitting on the same injected cases you evaluate on gives a beautiful,
  meaningless curve. CI will assert the separation.
- **Escape utilisation (`escape_used`)** is Week 11's schema question; it is
  always False today. Calibrate with it as a feature or a stratum, not
  ignored.
- **Version the curve with `ruleset_version`.** B7.4's baseline gate already
  refuses to diff across ruleset versions for the same reason: a different
  ruleset produces different findings, and a stale curve produces wrong
  probabilities without any error.

---

## First commit, per the rotation rule

Suggested non-trivial first commit: `verity/calibration/__init__.py` with a
`CalibrationCurve` model (method, ruleset_version, fitted_on split id,
thresholds) and a loader that **refuses** a curve whose ruleset or method does
not match — the same refuse-don't-guess shape as `load_baseline`. That gives
A12.1 somewhere to write to and A12.4 something to check.

I stay off this module for Phase 3. Questions are fine; commits are yours.
