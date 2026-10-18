"""
A4.4 — APG contract schema + loader.

The loader's one job is to refuse a malformed contract rather than load it as
an empty one: a silently-skipped pattern reports a clean bill of health it
never earned. These tests pin that, and confirm the shipped tablist contract
(Track B's half of the shared artifact) validates and carries the one
assertion Week 4's gate depends on — the roving-tabindex rule.
"""

import textwrap
from pathlib import Path

import pytest

from verity.rulepacks import (
    ApgContract,
    Severity,
    load_contract,
    load_contracts,
    CONTRACTS_DIR,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_shipped_tablist_contract_loads():
    contracts = load_contracts()
    assert "tablist" in contracts, "the hand-written tablist contract must load"
    tablist = contracts["tablist"]
    assert tablist.version >= 1
    assert "2.1.1" in tablist.wcag


def test_tablist_pins_the_roving_tabindex_rule():
    """
    The assertion that prevents Week 4's false alarm must be present and a hard
    violation. If it vanished, the contract would stop documenting the crux of
    the whole pattern.
    """
    tablist = load_contracts()["tablist"]
    roving = tablist.assertion("roving-tabindex")
    assert roving is not None, "the roving-tabindex assertion is the crux of the pattern"
    assert roving.severity is Severity.VIOLATION


def test_arrow_wrapping_is_a_warning_not_a_violation():
    """An optional APG behaviour must never be a build-gating violation."""
    tablist = load_contracts()["tablist"]
    wrap = tablist.assertion("arrow-wrapping-is-optional")
    assert wrap is not None
    assert wrap.severity is Severity.WARNING


def test_not_asserted_is_populated():
    """The deliberately-uncheckable list is a real section, not decoration."""
    tablist = load_contracts()["tablist"]
    assert len(tablist.not_asserted) >= 1


def test_unknown_key_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        contract: x
        version: 1
        structure:
          - id: a
            severity: violation
            assert: "something"
            bogus_key: nope
        """,
    )
    with pytest.raises(Exception):
        load_contract(path)


def test_bad_severity_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        contract: x
        version: 1
        keyboard:
          - id: a
            severity: catastrophe
            assert: "something"
        """,
    )
    with pytest.raises(Exception):
        load_contract(path)


def test_duplicate_assertion_id_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        contract: x
        version: 1
        structure:
          - id: dup
            severity: violation
            assert: "one"
          - id: dup
            severity: warning
            assert: "two"
        """,
    )
    with pytest.raises(Exception, match="duplicate assertion id"):
        load_contract(path)


def test_contract_dir_is_where_track_b_put_it():
    assert CONTRACTS_DIR.name == "apg-contracts"
    assert (CONTRACTS_DIR / "tablist.yaml").exists()
