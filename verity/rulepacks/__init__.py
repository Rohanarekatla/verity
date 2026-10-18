"""
A4.4 — APG contract schema and loader.

A *rulepack* is a machine-readable statement of what one ARIA Authoring
Practices pattern looks like when it is built correctly. The point is not the
loader; it is the discipline the plan commits us to (ADR-0004, rule 3):
**write the contract before the checking code.** Writing
`data/apg-contracts/tablist.yaml` by hand is what surfaced the roving-tabindex
false alarm that would otherwise have failed Week 4's gate — a checker that
only knows about Tab sees five unreachable tabs and cries wolf.

This module is the schema those hand-written contracts are validated against,
and the loader that reads them. It deliberately does **not** interpret or run
a contract — that is the interaction agent's job. It only guarantees that a
contract on disk is well-formed, so a typo in an assertion id or a missing
severity is caught at load time rather than silently skipping a check.

The schema mirrors the shape Track B wrote by hand, so the two halves of the
shared artifact validate against one definition rather than drifting.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Where the hand-written contracts live. Track B put the first one here; the
# loader follows that choice rather than inventing a second location.
CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "data" / "apg-contracts"


class Severity(str, Enum):
    """
    How hard an assertion bites.

    `violation` is a definite failure and may gate a build. `warning` covers
    the cases where a legitimate variant exists — it maps to
    `cantTell`/`NEEDS_REVIEW` downstream and can never fail a build. Keeping
    the two apart in the contract is what stops an optional APG behaviour
    (arrow-key wrapping, say) from being asserted as a hard failure.
    """

    VIOLATION = "violation"
    WARNING = "warning"


class Assertion(BaseModel):
    """One checkable (or deliberately-uncheckable) statement about a pattern."""

    # populate_by_name lets `assert_` be set by its Python name too; the YAML
    # key is `assert` (a Python keyword), handled by the alias.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    severity: Severity
    assert_: str = Field(alias="assert")
    note: Optional[str] = None
    # An assertion may pin itself to a specific SC, overriding the contract's
    # top-level list — `no-positive-tabindex` is 2.4.3 even on a contract whose
    # headline criteria are 2.1.1 and 4.1.2.
    wcag: Optional[str] = None


class ContractFixtures(BaseModel):
    """
    A9.4 — the two pages every contract ships with, relative to
    ``data/fixtures/``. `pass_` is a correct implementation the runner must
    report clean; `fail` is a broken one on which at least one `violation`
    must fail. A contract that cannot fail its own fail-fixture checks
    nothing, and the gate (`verity.agents.interaction.verify_contract_fixtures`)
    rejects it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pass_: str = Field(alias="pass")
    fail: str


class ApgContract(BaseModel):
    """
    A validated APG pattern contract.

    `not_asserted` is a first-class section, not a comment: it records what a
    machine cannot decide (whether a label is *meaningful*, whether tab order
    matches visual order) so a later version cannot quietly add such a check
    and start producing false alarms.
    """

    model_config = ConfigDict(extra="forbid")

    contract: str
    version: int = Field(ge=1)
    source: list[str] = []
    wcag: list[str] = []
    match: dict = {}
    structure: list[Assertion] = []
    keyboard: list[Assertion] = []
    not_asserted: list[str] = []
    reference_implementations: list[str] = []
    # Optional at load time so a draft contract can be written before its
    # fixtures; the A9.4 gate is what refuses to ship one without them.
    fixtures: Optional[ContractFixtures] = None

    @field_validator("structure", "keyboard")
    @classmethod
    def _assertion_ids_unique(cls, items: list[Assertion]) -> list[Assertion]:
        ids = [a.id for a in items]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            # A duplicate id means one assertion silently shadows another when
            # results are keyed by id — a dropped check that looks like a pass.
            raise ValueError(f"duplicate assertion id(s): {dupes}")
        return items

    def assertion(self, assertion_id: str) -> Optional[Assertion]:
        """Look up one assertion by id across both sections, or None."""
        for a in (*self.structure, *self.keyboard):
            if a.id == assertion_id:
                return a
        return None


def load_contract(path: Path) -> ApgContract:
    """
    Load and validate one contract file.

    Raises on anything malformed — an unknown key (``extra='forbid'``), a bad
    severity, a duplicate assertion id. A contract that does not parse is not
    loaded as an empty one: a silently-skipped pattern is a checker that
    reports a clean bill of health it never earned.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: top level must be a mapping, got {type(data).__name__}")
    return ApgContract.model_validate(data)


def load_contracts(directory: Optional[Path] = None) -> dict[str, ApgContract]:
    """
    Load every ``*.yaml`` contract in a directory, keyed by contract name.

    A duplicate `contract:` name across two files is an error, not a
    last-one-wins merge — it would make which pattern is in force depend on
    filesystem ordering.
    """
    directory = directory or CONTRACTS_DIR
    out: dict[str, ApgContract] = {}
    for path in sorted(directory.glob("*.yaml")):
        contract = load_contract(path)
        if contract.contract in out:
            raise ValueError(
                f"two contracts both named '{contract.contract}' "
                f"({path.name} and an earlier file)"
            )
        out[contract.contract] = contract
    return out
