"""
Track A leftovers finished on Track B's side (2026-10-30, Rohan out of usage):
the keyboard/focus defect family for H3 and its verification, and the
ruleset fingerprint that keeps the findings cache from serving stale results.
"""

import shutil
from pathlib import Path

from eval.agentbench.runner import DEFECT_FAMILY
from eval.agentbench.tasks import KEYBOARD_DEFECTS, MINIWOB_TASKS, summary
from eval.agentbench.verify_injection import assess_change, assess_keyboard
from verity.crawl.cache import ruleset_fingerprint

REPO = Path(__file__).resolve().parents[2]


def probe(*ids, indicator=True):
    return [{"id": i, "indicator": indicator} for i in ids]


def test_trap_manifests_when_focus_never_leaves_the_first_control():
    clean = probe("#a", "#b", "#c", "#a", "#b", "#c")
    assert assess_keyboard(clean, probe(*["#a"] * 6), "keyboard_trap").manifested
    assert not assess_keyboard(clean, clean, "keyboard_trap").manifested


def test_tab_loss_manifests_when_fewer_controls_are_reachable():
    clean = probe("#a", "#b", "#c")
    assert assess_keyboard(clean, probe(None, None, None), "remove_from_tab_order").manifested
    assert not assess_keyboard(clean, clean, "remove_from_tab_order").manifested


def test_focus_indicator_loss_needs_a_ring_on_clean_and_none_on_defect():
    clean = probe("#a", "#b")
    assert assess_keyboard(clean, probe("#a", "#b", indicator=False), "outline_none").manifested
    assert not assess_keyboard(probe("#a", indicator=False), probe("#a", indicator=False), "outline_none").manifested


def test_a_page_with_nothing_focusable_cannot_verify_a_keyboard_defect():
    assert not assess_keyboard(probe(None, None), probe(None, None), "remove_from_tab_order").manifested


def test_tree_comparison_refuses_keyboard_defects():
    a = assess_change('[1] button "Go"', '[1] button "Go"', "keyboard_trap")
    assert not a.manifested and "tab_probe" in a.detail


def test_keyboard_family_is_in_the_suite_and_the_analysis_families():
    assert set(KEYBOARD_DEFECTS) <= set(summary()["defect_coverage"])
    assert all(DEFECT_FAMILY[d] in ("keyboard", "focus") for d in KEYBOARD_DEFECTS)
    assert sum(1 for t in MINIWOB_TASKS if set(KEYBOARD_DEFECTS) <= set(t.defects)) >= 4


def test_defects_js_defines_every_runtime_defect():
    js = (REPO / "eval" / "agentbench" / "defects.js").read_text(encoding="utf-8")
    for name in ("strip_name", "div_button", "detach_label", *KEYBOARD_DEFECTS):
        assert f"{name}:" in js or f"{name}: " in js


def test_ruleset_fingerprint_changes_when_a_contract_changes(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "data" / "apg-contracts", repo / "data" / "apg-contracts")
    (repo / "pyproject.toml").write_text("[project]\nname='verity'\n", encoding="utf-8")
    first = ruleset_fingerprint(repo)
    assert first == ruleset_fingerprint(repo), "stable when nothing changed"
    tab = repo / "data" / "apg-contracts" / "tablist.yaml"
    tab.write_text(tab.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert ruleset_fingerprint(repo) != first
    (repo / "waivers.yaml").write_text("x: 1\n", encoding="utf-8")
    assert ruleset_fingerprint(repo) not in (first,)
