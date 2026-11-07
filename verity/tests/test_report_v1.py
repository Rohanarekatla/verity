"""B12.2′ / B12.3′ (Track B, Week 12) — the pre-registered results tables and cost model."""

from eval.agentbench.analysis import EpisodeRecord
from eval.agentbench.report_v1 import (
    cost_model,
    did_table,
    exclusions,
    h1_table,
    h4_table,
    kill_check,
    render_markdown,
)


def ep(task, defect, outcome, trial=0, agent="tree", model="m", family="name", **kw):
    return EpisodeRecord(
        episode_id=f"{agent}|{model}|{task}|{defect}|t{trial}", task_id=task, app="miniwob", defect=defect,
        defect_family=None if defect == "clean" else family, agent=agent, provider="ollama", model=model,
        trial=trial, outcome=outcome, **kw)


def run(n_tasks=6, trials=5, defect_fails=4, agent="tree", defect="strip_name", family="name", **kw):
    """Clean always succeeds; the defect fails `defect_fails` of `trials` per task."""
    rs = []
    for t in range(n_tasks):
        for i in range(trials):
            rs.append(ep(f"t{t}", "clean", "success", i, agent=agent, **kw))
            rs.append(ep(f"t{t}", defect, "failure" if i < defect_fails else "success", i, agent=agent,
                         family=family, **kw))
    return rs


def test_kill_check_reads_clean_success_of_the_best_model():
    k = kill_check(run() + [ep("t0", "clean", "failure", 9, model="weak")])
    assert k["passed"] and k["best"] == 1.0
    assert not kill_check([ep("t0", "clean", "failure")])["passed"]


def test_h1_supported_when_every_test_agrees():
    rows = h1_table(run(), n_boot=300)
    assert len(rows) == 1 and rows[0]["supported"] and not rows[0]["unreliable"]
    assert rows[0]["family_size"] == 1


def test_h1_no_effect_is_not_supported():
    rows = h1_table(run(defect_fails=0), n_boot=300)
    assert not rows[0]["supported"]


def test_a_cell_losing_more_than_10_percent_of_pairs_is_unreliable_and_leaves_the_family():
    rs = run()
    rs = [r.model_copy(update={"excluded_reason": "provider_error"}) if r.defect != "clean" and r.trial == 0 else r
          for r in rs]
    rows = h1_table(rs, n_boot=200)
    assert rows[0]["unreliable"] and rows[0]["holm_p"] is None and rows[0]["family_size"] == 0
    assert not rows[0]["supported"]


def test_h2_is_not_tested_without_the_second_agent():
    d = did_table(run(), agent_x="tree", agent_y="browser_use", families=("name",), n_boot=100)
    assert not d["tested"] and "browser_use" in d["why"]


def test_h2_difference_in_differences_when_both_agents_ran():
    rs = run(agent="tree") + run(agent="browser_use", defect_fails=0)
    d = did_table(rs, agent_x="tree", agent_y="browser_use", families=("name",), n_boot=200)
    assert d["tested"] and d["rows"][0]["did"] > 0


def test_h3_needs_keyboard_defects():
    rs = run(agent="tree") + run(agent="screen_reader")
    d = did_table(rs, agent_x="screen_reader", agent_y="tree", families=("keyboard", "focus"), n_boot=100)
    assert not d["tested"] and "keyboard" in d["why"]


def test_h4_and_cost_model_charge_failures():
    rs = []
    for i in range(4):
        rs.append(ep("t0", "clean", "success", i, input_tokens=100, cost_usd=0.01, steps=2))
        rs.append(ep("t0", "strip_name", "success" if i == 0 else "failure", i, input_tokens=300,
                     cost_usd=0.03, steps=6))
    h4 = {r["defect"]: r for r in h4_table(rs)}["strip_name"]
    assert h4["clean_tokens_per_success"] == 100 and h4["defect_tokens_per_success"] == 1200
    cm = {r["defect"]: r for r in cost_model(rs)}
    assert cm["clean"]["cost_per_success"] == 0.01
    assert abs(cm["strip_name"]["cost_per_success"] - 0.12) < 1e-9
    assert abs(cm["strip_name"]["cost_per_success_vs_clean"] - 12.0) < 1e-9
    assert cm["strip_name"]["tokens_per_step"] == 50


def test_nothing_succeeded_is_not_free():
    cm = cost_model([ep("t0", "clean", "failure", cost_usd=0.02)])
    assert cm[0]["cost_per_success"] is None


def test_exclusions_count_indeterminate_separately():
    rs = [ep("t0", "clean", "indeterminate"), ep("t1", "clean", "success", excluded_reason="budget")]
    assert exclusions(rs) == {"budget": 1, "indeterminate": 1}


def test_markdown_has_every_preregistered_section_in_order():
    md = render_markdown(run(), n_boot=100)
    order = ["## 1. Kill criterion", "## 3. H1", "## 4. H2", "## 4. H3", "## 5. H4", "## 6. Exclusions",
             "## Cost model"]
    positions = [md.index(h) for h in order]
    assert positions == sorted(positions)
    assert "Not tested" in md
