# data/apg-contracts/

YAML interaction contracts for ARIA design patterns — the expected
structure and keyboard behaviour for each pattern, written by hand against
the ARIA Authoring Practices Guide **before** the checking code (ADR-0004,
rule 3). Validated by `verity/rulepacks/` (A4.4) and executed by the contract
runner in `verity/agents/interaction.py` (A9.1).

| Contract | Author | Pass / fail fixtures (`data/fixtures/`) |
|---|---|---|
| `tablist.yaml` | Track B (Week 4) | `apg/tablist-pass.html` / `apg/tablist-fail.html` |
| `disclosure.yaml` | Track A (Week 9) | `apg/disclosure-pass.html` / `apg/disclosure-fail.html` |
| `menu-button.yaml` | Track A (Week 9) | `apg/menu-button-pass.html` / `apg/menu-button-fail.html` |

Week 9 asks for five; the remaining two (dialog, combobox) are Track B's half
and the joint fifth.

## Adding a contract

1. Write the YAML first — `match`, `structure`, `keyboard`, and
   `not_asserted` for every judgment a machine cannot make. Severity is
   `violation` (may gate) or `warning` (review only, never gates).
2. `match` keys: `role` (one or a list), `has` / `lacks` (attribute names),
   `values` (attribute -> allowed values), `controls_not` (roles the
   aria-controls target must not have). Unknown keys are an error.
3. Ship **both** fixtures under `fixtures:`. The A9.4 gate
   (`verity/tests/test_contract_gate.py`) rejects a contract unless the runner
   reports zero failures — and decides every implemented violation — on the
   pass fixture, and fails at least one violation on the fail fixture.
4. Add its checks to `CHECKS` in `verity/agents/interaction.py`. Until then
   every assertion reports `notChecked` — never a pass.
