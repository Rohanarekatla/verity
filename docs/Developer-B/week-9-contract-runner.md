# Nikhil — Week 9: the contract runner is in; three things on your side

**From Rohan.** Track A's Week 9 (A9.1–A9.4) is on branch
`rohan-week9-interaction`. This note is what you need to build on it.

## What landed

| # | What | Where |
|---|---|---|
| A9.2 | `inventoryWidgets` RPC — explicit-ARIA widgets only, blind spots counted | `node-worker/interaction/widgets.ts` |
| A9.1 | `exerciseWidget` RPC — play focus/key steps, snapshot after each | same file |
| A9.1 | Contract runner — match by role, plan keys, one verdict per assertion | `verity/agents/interaction.py` |
| A9.3 | Per-step timeout, per-widget step + time budget, navigation stop, per-page widget cap | worker + `InteractionBudget` |
| A9.4 | Contracts declare `fixtures: {pass, fail}`; the gate rejects any contract that doesn't fail its fail-fixture | `verify_contract_fixtures`, `test_contract_gate.py` |
| — | Track A's two contracts: `disclosure.yaml`, `menu-button.yaml` | `data/apg-contracts/` |
| — | Checks for **your** `tablist.yaml` too, plus pass/fail fixtures for it | `apg/tablist-*.html` |

The new models (`WidgetNode`, `Widget`, `WidgetInventory`, `InteractionStep`,
`InteractionSnapshot`, `ExerciseResult`) are in `schemas.py`, exported, and in
the generated TS mirror — the drift test covers them.

## The only edit to your file

`tablist.yaml` gained a `fixtures:` block at the bottom (A9.4 requires one).
No assertion was changed. Two of its assertions report `notChecked` on
purpose — please sanity-check the reasoning:

- `tablist-owns-tabs` — ownership is *how* the inventory finds tabs, so the
  inventory cannot also check it. Needs an independent DOM walk if we want it.
- `focus-visible-on-tabs` — already measured by the traversal (A4.3 →
  `keyboard.py` SC 2.4.7); running it twice would double-report.

## Your side

1. **Your two contracts + the joint fifth.** Dialog and combobox are what's
   left of the README's five. The runner tells you exactly what's missing: a
   contract with no entry in `CHECKS` reports every assertion `notChecked`,
   and the gate fails it until it ships fixtures that behave.
2. **Wire it into `scan_url()`** — same shape as BC-A1:
   `run_contracts_on_artifact(rpc_call, artifact_id)` then
   `to_findings(run, content_hash)`. It **mutates the page** (it presses
   keys), so it must run *after* axe, contrast sampling and
   `traverseTabOrder`, before `releaseArtifact`. Wrap it in the same
   graceful fallback — a worker without `inventoryWidgets` means no
   interaction findings, never fabricated ones.
3. **Cross-check** `disclosure.yaml` and `menu-button.yaml` at the pair
   session, as the plan asks. Where you disagree on what "correct" is, that's
   the useful part. The judgment calls I'd most like a second opinion on:
   - `expanded-state-matches-visibility` is a **warning** (collapse
     animations keep content rendered for a moment).
   - Menu button: Escape/ArrowDown are `cantTell` (not `fail`) when Enter
     didn't move focus into the menu — their precondition was never reached.
   - Menu button: only `aria-expanded=true` while open is asserted; the APG
     recommends removing it when closed, so closed-state is not checked.

## Findings mapping (`to_findings`)

| result | outcome | provenance |
|---|---|---|
| violation fail | fail | AUTHORITATIVE |
| any pass | pass | AUTHORITATIVE |
| warning fail | cantTell | NEEDS_REVIEW |
| cantTell | cantTell | NEEDS_REVIEW |
| notChecked | (no finding) | |

Assertions without their own `wcag:` default to 4.1.2 (structure) or 2.1.1
(keyboard). `rule_id` is `apg-<contract>-<assertion>`, so dedup sees each
assertion separately.
