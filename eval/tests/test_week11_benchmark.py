"""
A11.2′ (injection verification) + A11.1′ (task suite).

The verification logic (does the tree change in the direction the defect
intends?) is tested on synthetic AXTree text — no browser. A skippable real-env
test drives the actual injection and adds the pixel check. The task suite is
checked for shape: every cell has a meaningful defect, success is the env
reward, and the enumerated matrix is the size the pre-registration expects.
"""

import pytest

from eval.agentbench.tasks import (
    MINIWOB_TASKS,
    Task,
    available,
    cells,
    summary,
)
from eval.agentbench.verify_injection import (
    assess_change,
    parse_tree,
)


# --- A11.2′ verification logic (pure) --------------------------------------

def test_strip_name_manifests_as_a_lost_name():
    before = '[1] button "Save"\n[2] textbox "Email"'
    after = '[1] button\n[2] textbox "Email"'   # the button lost its name
    a = assess_change(before, after, "strip_name")
    assert a.manifested and a.before_named == 2 and a.after_named == 1


def test_detach_label_manifests_as_a_lost_control_name():
    before = '[2] textbox "Email"\n[3] checkbox "Agree"'
    after = '[2] textbox\n[3] checkbox "Agree"'
    assert assess_change(before, after, "detach_label").manifested


def test_div_button_manifests_as_role_loss():
    before = '[1] button "Go"\n[2] link "Home"'
    after = '[5] generic "Go" (clickable)\n[2] link "Home"'  # button gone, roleless clickable appears
    assert assess_change(before, after, "div_button").manifested


def test_defect_that_did_not_manifest_is_caught():
    tree = '[1] button "Save"'
    a = assess_change(tree, tree, "strip_name")
    assert not a.manifested and "no name was lost" in a.detail


def test_div_button_not_manifested_when_button_survives():
    before = '[1] button "Go"'
    after = '[1] button "Go"'
    assert not assess_change(before, after, "div_button").manifested


def test_unknown_defect_is_not_manifested():
    assert not assess_change("[1] button \"x\"", "[1] button", "teleport").manifested


def test_parse_tree_handles_bids_names_and_clickable():
    nodes = parse_tree('  [1] button "Save" (focused)\n  [2] generic "x" (clickable)\n  text')
    assert nodes[0].bid == "1" and nodes[0].role == "button" and nodes[0].name == "Save"
    assert nodes[1].role == "generic" and nodes[1].clickable is True


# --- A11.1′ task suite shape -----------------------------------------------

def test_suite_is_the_preregistered_size():
    s = summary()
    assert 20 <= s["tasks"] <= 30, f"plan calls for 20-30 tasks, got {s['tasks']}"
    # Every family represented.
    assert set(s["families"]) == {"button", "link", "select", "form"}
    # All three defects are exercised.
    assert set(s["defect_coverage"]) == {"strip_name", "div_button", "detach_label"}


def test_every_task_declares_at_least_one_defect_and_env_reward():
    for t in MINIWOB_TASKS:
        assert t.defects, f"{t.id} has no applicable defect — it would be a wasted cell"
        assert t.success == "env-reward"


def test_cells_yields_clean_plus_each_defect():
    t = Task("x", "miniwob", "button", ("strip_name", "div_button"))
    got = list(cells((t,)))
    assert got == [(t, None), (t, "strip_name"), (t, "div_button")]


def test_cells_can_omit_the_clean_control():
    t = Task("x", "miniwob", "button", ("strip_name",))
    assert list(cells((t,), include_clean=False)) == [(t, "strip_name")]


def test_available_filters_to_present_html(tmp_path):
    # None of these exist under tmp_path, so availability is empty there.
    assert available(MINIWOB_TASKS, html_dir=tmp_path) == []


# --- A11.2′ real injection (skipped without Chromium + vendored tasks) ------

def _real_env_available() -> bool:
    from eval.agentbench.env import MINIWOB, chromium_path

    return chromium_path() is not None and (MINIWOB / "click-button.html").exists()


@pytest.mark.skipif(not _real_env_available(), reason="needs Chromium + the vendored MiniWoB tasks")
def test_strip_name_verifies_on_a_real_button_task():
    from eval.agentbench.env import MiniWoBEnv
    from eval.agentbench.verify_injection import verify

    with MiniWoBEnv(headless=True) as env:
        result = verify(env, "click-button", seed=1, defect="strip_name")
    # The defect must manifest in the tree AND leave the pixels unchanged.
    assert result.assessment is not None and result.assessment.manifested, result.reasons
    assert result.pixels_identical is True, "strip_name must be invisible to a sighted user"
    assert result.ok is True
