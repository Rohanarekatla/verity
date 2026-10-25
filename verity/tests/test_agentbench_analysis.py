"""
B11.3′ (Track B, Week 11) — the pre-registered analysis code.

Reference values are textbook results (Wilson 5/10, exact McNemar 10 vs 2,
Wilcoxon on 1..5) so a regression in the statistics is caught, not just a
crash. Pairing and exclusion rules are pinned because they decide what the
headline number means.
"""

import pytest

from eval.agentbench.analysis import (
    EpisodeRecord,
    cluster_bootstrap,
    difference_in_differences,
    holm,
    load_records,
    mcnemar_exact,
    mcnemar_pairs_needed,
    pair_episodes,
    paired_diff_ci,
    paired_effect,
    pilot_summary,
    tokens_per_success,
    wilcoxon_signed_rank,
    wilson,
)


# --- statistics against known values ---------------------------------------------

def test_wilson_interval_textbook_value():
    p, lo, hi = wilson(5, 10)
    assert (p, round(lo, 4), round(hi, 4)) == (0.5, 0.2366, 0.7634)


def test_wilson_never_leaves_0_1():
    assert 0.0 <= wilson(0, 10)[1] < 1e-12 and 1 - 1e-12 < wilson(10, 10)[2] <= 1.0


def test_exact_mcnemar_textbook_value():
    # 12 discordant pairs split 10 / 2: P = 2 * (1 + 12 + 66) / 4096
    assert mcnemar_exact(10, 2) == pytest.approx(2 * 79 / 4096)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(3, 3) == 1.0


def test_paired_interval_is_never_degenerate():
    # No discordant pairs is "no evidence of a difference", not certainty.
    point, lo, hi = paired_diff_ci(10, 0, 0, 10)
    assert point == 0.0 and lo < 0 < hi
    point, lo, hi = paired_diff_ci(20, 10, 2, 8)
    assert point == pytest.approx(0.2) and lo < 0.2 < hi and 0 < lo


def test_holm_adjustment_is_monotone_and_capped():
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == {"a": 0.03, "c": 0.06, "b": 0.06}
    assert holm({"x": 0.9, "y": 0.8}) == {"y": 1.0, "x": 1.0}


def test_sample_size_for_mcnemar():
    # psi = 0.30, delta = 0.20, alpha 0.05 two-sided, power 0.8 -> 57 pairs (Connor 1987)
    assert mcnemar_pairs_needed(0.25, 0.05) == 57
    with pytest.raises(ValueError):
        mcnemar_pairs_needed(0.1, 0.1)


def test_wilcoxon_signed_rank_normal_approximation():
    r = wilcoxon_signed_rank([1, 2, 3, 4, 5])
    assert r["w_plus"] == 15 and r["p"] == pytest.approx(0.0431, abs=1e-4)
    assert wilcoxon_signed_rank([0, 0])["p"] == 1.0


def test_cluster_bootstrap_is_reproducible():
    clusters = {"t1": [1.0, 1.0], "t2": [0.0], "t3": [1.0, 0.0]}
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    assert cluster_bootstrap(clusters, mean, n_boot=500, seed=1) == cluster_bootstrap(clusters, mean, n_boot=500, seed=1)


# --- pairing and exclusions --------------------------------------------------------

def ep(task, defect, outcome, trial=0, agent="tree", model="qwen3:8b", **kw):
    return EpisodeRecord(episode_id=f"{task}-{defect}-{trial}-{agent}", task_id=task, app="miniwob",
                         defect=defect, agent=agent, provider="ollama", model=model, trial=trial,
                         outcome=outcome, **kw)


def test_pairs_match_task_agent_model_and_trial():
    rs = [ep("t1", "clean", "success", 0), ep("t1", "div_button", "failure", 0),
          ep("t1", "clean", "success", 1), ep("t1", "div_button", "success", 1)]
    pairs, dropped = pair_episodes(rs, defect="div_button", agent="tree", model="qwen3:8b")
    assert sorted(pairs) == [("t1", True, False), ("t1", True, True)] and dropped == 0


def test_an_excluded_half_drops_the_whole_pair():
    rs = [ep("t1", "clean", "success"), ep("t1", "div_button", "indeterminate"),
          ep("t2", "clean", "success", excluded_reason="provider_error"), ep("t2", "div_button", "failure")]
    pairs, dropped = pair_episodes(rs, defect="div_button", agent="tree", model="qwen3:8b")
    assert pairs == [] and dropped == 2


def test_paired_effect_reports_everything_results_v1_needs():
    rs = []
    for t in ("t1", "t2", "t3"):
        for trial in range(4):
            rs += [ep(t, "clean", "success", trial), ep(t, "strip_name", "failure" if trial < 3 else "success", trial)]
    pairs, dropped = pair_episodes(rs, defect="strip_name", agent="tree", model="qwen3:8b")
    e = paired_effect(pairs, dropped, n_boot=300)
    assert (e["pairs"], e["tasks"], e["b_clean_only"], e["c_defect_only"]) == (12, 3, 9, 0)
    assert e["diff"] == pytest.approx(0.75)
    assert e["mcnemar_p"] == pytest.approx(2 / 2 ** 9)
    assert e["diff_ci"][0] > 0 and e["diff_ci_cluster_bootstrap"][0] <= e["diff"] <= e["diff_ci_cluster_bootstrap"][1]


def test_difference_in_differences_for_agent_types():
    tree = [("t1", True, False), ("t2", True, False)]
    vision = [("t1", True, True), ("t2", True, True)]
    r = difference_in_differences(tree, vision, n_boot=200)
    assert r["tasks"] == 2 and r["did"] == pytest.approx(1.0)


def test_tokens_per_success_charges_failures_too():
    rs = [ep("t1", "clean", "success", input_tokens=100), ep("t1", "clean", "failure", trial=1, input_tokens=300)]
    assert tokens_per_success(rs) == 400
    assert tokens_per_success([ep("t1", "clean", "failure")]) is None


# --- the pilot (W10 gate) -----------------------------------------------------------

def test_pilot_summary_sizes_week_12_from_observed_discordance():
    rs = []
    for trial in range(10):
        rs.append(ep("t1", "clean", "success", trial, input_tokens=1000, cost_usd=0.01))
        rs.append(ep("t1", "div_button", "failure" if trial < 4 else "success", trial, input_tokens=1500,
                     cost_usd=0.015))
    s = pilot_summary(rs)
    cells = {c["defect"]: c for c in s["cells"]}
    assert cells["clean"]["episodes"] == 10 and cells["div_button"]["tokens_mean"] == 1500
    sizing = s["sizing"][0]
    assert sizing["p10"] == pytest.approx(0.4) and sizing["p01"] == 0
    assert sizing["pairs_needed"] >= mcnemar_pairs_needed(0.4, 0.0)
    assert s["cost_total"] == pytest.approx(0.25)


def test_records_round_trip_through_jsonl(tmp_path):
    path = tmp_path / "episodes.jsonl"
    path.write_text("\n".join(ep("t1", "clean", "success").model_dump_json() for _ in range(2)) + "\n",
                    encoding="utf-8")
    assert len(load_records(path)) == 2
