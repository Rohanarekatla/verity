# Rohan — Week 9, Track B is in

**From Nikhil.** Reply to `docs/Developer-B/week-9-contract-runner.md`.
Everything below is on my branch with the B7.4 / E2E-fix work.

## What landed

| # | What | Where |
|---|---|---|
| — | **dialog** contract (matched on the trigger: `aria-haspopup="dialog"`) | `data/apg-contracts/dialog.yaml`, `apg/dialog-{pass,fail}.html` |
| — | **combobox** contract (listbox popup; editable + select-only) | `data/apg-contracts/combobox.yaml`, `apg/combobox-{pass,fail}.html` |
| — | Checks for both in `CHECKS` | `verity/agents/interaction.py` |
| B9.1 | Announcement prediction: name, role, states → "Show details, button, collapsed" | `verity/agents/announce.py` |
| B9.1/B9.3 | Inventory names now come from **Chromium's computed accessible name** (CDP `getPartialAXTree`), shadow DOM included | `node-worker/interaction/accname.ts` |
| B9.2 | Virtual screen reader: browse-mode transcript of `ax-tree.json`, pure Python | `verity/agents/virtual_sr.py` |
| B9.4 | Six ARIA-misuse injectors + the "all injected misuse fails" test | `eval/inject/aria_misuse.py`, `verity/tests/test_aria_misuse.py` |
| — | Rotation #2 handover: confidence & calibration → you | `docs/handover/confidence-calibration.md` |

That makes the five: tablist, disclosure, menu-button, dialog, combobox.

## Changes to your files, so you are not surprised

All small and additive. Tell me if you want any of them done differently.

1. **`interaction.py`** — `PatternChecks` gained an optional `watch` field
   and `_watch(widget, checks)` includes it. Dialog watches
   `#dlg:focus-within` (it shows up in `missing` when focus leaves the
   dialog); combobox watches its popup by `[id="…"]`, because many popups
   only exist once opened. Existing contracts pass nothing, so nothing
   changes for them.
2. **`widgets.ts`** — `listbox: ["option"]` in `CONTAINER_ITEMS`, and a
   `role === "combobox"` branch that takes items from the popup it controls
   (`aria-controls`, or `aria-owns` for ARIA 1.0). Your header comment says
   a new contract needs its role there; that is all this is.
3. **`widgets.ts` `inventoryWidgets`** — after the in-page pass, calls
   `withComputedNames` (`accname.ts`). Rules: a node the browser reports as
   *ignored* (a closed menu's items) keeps your in-page guess; a rendered node
   takes the browser's name, **including an empty one**; any CDP error leaves
   the inventory exactly as before. Without this, the APG's own combobox
   examples (`<label for>`) would fail "has an accessible name". Same for
   `<img alt>` inside a button, `aria-hidden` decorations, and custom elements
   labelled in their shadow root — `data/fixtures/accname-shadow.html` pins
   all four.
4. **`eval/apg_reference_check.py`** — added the dialog and four combobox
   APG pages, as you asked. I could not run it from here (no network
   browser); please run it at the pair session.
5. **`test_contract_gate.py`** — "the first contracts" now lists all five.

## Judgment calls I would like a second opinion on (my half of the cross-check)

- **Dialog is matched on the trigger, not on `role=dialog`.** A closed dialog
  is not rendered, and the only non-speculative link from a button to a
  dialog is `aria-haspopup="dialog"`. The APG's own dialog example declares
  nothing, so it matches **zero** widgets — honest, but it means that
  reference page proves "no false alarm", not "the contract works".
- **Tab containment is judged only for `aria-modal="true"`.** Focus going to
  "nowhere" (native `showModal()` sending it to the address bar) is not an
  escape. Escape and focus-return are warnings.
- **Combobox `arrow-keys-reach-options` gates only for select-only.** On an
  editable combobox the user can type the value, so unreachable options are
  an APG deviation.
- **Absent `aria-expanded` on a combobox is APG_ONLY**, an invalid value is a
  violation; `expanded-true-when-open` catches a state that is actually wrong.
- A date-picker combobox (dialog popup) is cantTell on option and
  focus-stays checks — it takes focus by design.

## Your three questions

- `expanded-state-matches-visibility` as a **warning** — agree; I would have
  made the same call for the same reason (collapse animations).
- Menu button Escape/ArrowDown **cantTell** when Enter never moved focus in —
  agree; it is exactly "a precondition never reached is not evidence".
- Only `aria-expanded=true` while open — agree.
- And the two `notChecked` on tablist (`tablist-owns-tabs`,
  `focus-visible-on-tabs`) — agree with both; double-reporting 2.4.7 would be
  worse than not checking it here.

## What only runs with the worker built

```
cd node-worker && npm ci && npm run build && cd ..
uv run pytest verity/tests/test_contract_gate.py verity/tests/test_aria_misuse.py verity/tests/test_virtual_sr.py -v
uv run python eval/apg_reference_check.py      # network; for the pair session
```

The gate tests are the ones that matter for Sunday: five contracts clean on
their pass fixtures and failing their fail fixtures (A9.4), and all twelve
injected misuses failing a violation (B9.4).
