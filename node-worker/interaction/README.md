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

Implemented in Week 9 (A9.1–A9.3):

- `widgets.ts` — `inventoryWidgets(page)` (A9.2): every widget with
  **explicit** ARIA semantics — a container role (`tablist`, `menu`,
  `menubar`) with the items it owns, or a `button` carrying `aria-expanded` /
  `aria-haspopup` with the items of whatever it `aria-controls`. Nothing is
  inferred from class names or layout. Shadow roots and iframes are counted
  as blind spots, not silently skipped.
- `exerciseWidget(page, {steps, watch})` (A9.1): plays `focus` / `press`
  steps and snapshots the watched elements (attributes, visibility, active
  element) after each. A9.3 guards: per-step timeout (2 s), a step budget, a
  wall-clock budget, and a stop when a step navigates the page away — each
  reported as `complete: false` with a reason.
- Exposed as the `inventoryWidgets` and `exerciseWidget` RPC methods.
  `exerciseWidget` **mutates** the page, so it runs after axe, sampling and
  the tab-order traversal.
- The verdicts live in `verity/agents/interaction.py` (the contract runner),
  judged against `data/apg-contracts/*.yaml`.
