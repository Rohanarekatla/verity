# node-worker/interaction/

Interaction Agent — drives the keyboard against ARIA APG contracts:
tab-order capture, multi-cycle keyboard-trap detection, focus-visible
via before/after diff. This is the ~2.49% frontier that automated
tools essentially don't address.

Implemented in Week 4 (A4.1–A4.3):

- `traverse.ts` — `traverseTabOrder(page, opts)`: presses Tab, records each
  focus stop (selector, bbox, role, accessible name, **authored** tabindex,
  dom order), detects keyboard traps over N cycles (N pinned by measurement in
  `docs/measurements/keyboard-trap-cycles.md`), and classifies anything Tab
  never reached — crucially marking roving-tabindex children `arrow-navigable`
  rather than as a barrier. `measureFocusVisible` adds the A4.3 focus-visible
  signal via a focused-vs-baseline computed-style diff.
- Exposed as the `traverseTabOrder` RPC method (`rpc/handlers.ts`).
- The verdicts (SC 2.1.1/2.1.2/2.4.3/2.4.7) live on the Python side in
  `verity/agents/keyboard.py`; nothing here decides conformance.

APG contracts live in `data/apg-contracts/`; the schema + loader are
`verity/rulepacks/` (A4.4).
