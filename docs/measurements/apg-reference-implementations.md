# APG reference implementations vs the contract runner

**Measured 2026-10-18** (Track A, Week 9) with `eval/apg_reference_check.py`
against the live W3C APG examples. Week 9's gate requires zero false alarms
on reference implementations; any failure here is a bug in our checker.

## First run — two false alarms, both fixed

| Page | False alarm | Cause | Fix |
|---|---|---|---|
| `tabs-actions` | `menu-button / trigger-in-tab-sequence` fail ×3 | Action buttons inside the tablist carry `tabindex=-1` and are reached with the arrow keys — the roving-tabindex trap again | Inventory reports `roving_ancestor`; a `-1` trigger under one is `cantTell`, same rule as `ARROW_NAVIGABLE` in the traversal |
| `menu-button-actions-active-descendant` | `menu-button / open-focuses-first-item` fail | DOM focus moves to the `menu`, and `aria-activedescendant` names the item — a documented APG variant | The runner treats "menu focused + activedescendant names item X" as being on X |

Neither variant was in our own pass fixtures, which is exactly why this run
exists.

## After the fixes

| Page | Widgets matched | Failures | cantTell |
|---|---|---|---|
| tabs-automatic | tablist ×1 | 0 | 0 |
| tabs-manual | tablist ×1 | 0 | 0 |
| tabs-actions | tablist ×1, menu-button ×4 | 0 | 3 (`trigger-in-tab-sequence`, arrow-reached by design) |
| disclosure-faq | disclosure ×4 | 0 | 0 |
| disclosure-image-description | disclosure ×1 | 0 | 0 |
| menu-button-actions | menu-button ×1 | 0 | 0 |
| menu-button-actions-active-descendant | menu-button ×1 | 0 | 0 |
| menu-button-links | menu-button ×1 | 0 | 0 |

**0 failures across 8 reference pages.** Not yet covered: dialog and
combobox (no contracts yet), and the "injected misuse fails" half of the gate
(needs B9.4's injectors).
