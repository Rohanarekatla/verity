# ADR-0010: Submit the ACT implementation report, or defer

**Status:** PROPOSED (2026-10-30) — decided jointly at the Week 15 pair
session; this records the proposal and the rule, not the outcome.

## Context

The W3C ACT implementation report is the cheapest credibility an unknown
open-source tool can earn. Verity has an ACT runner (`eval/act_runner.py`,
A15.3) that maps outcomes honestly — `cantTell` is never scored as a pass —
and an EARL 1.0 generator (`verity/report/earl.py`, B15.3).

## Proposal

1. Measure the per-rule pass rate on a pinned slice of the W3C ACT test cases
   (consistent implementations only count where every case agrees).
2. **Submit** if the report would list at least one rule as a *consistent*
   implementation — whatever the overall pass rate. A partial, honest report is
   more credible than none.
3. **Defer** only if no rule is consistent; record the measured numbers in
   `docs/measurements/act-pass-rate.md` either way.
4. Never tune a rule to an ACT case it fails without a fix that holds on the
   real-site corpus too.

## Consequences

The measured pass rate is published in both outcomes (plan: "measured and
published honestly, whatever the number is").

## Signatures

- Nikhil — proposed 2026-10-30
- Rohan — ____
