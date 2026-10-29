"""
A12.2′ — the results store and dashboards.

Proves the Parquet round-trip is lossless (JSON lines stays the source of truth,
Parquet is a faithful derived copy), the success matrix counts usable episodes
and exclusions correctly, the paired gap comes straight from the pre-registered
analysis, and both dashboards render from the records alone.
"""

from eval.agentbench.analysis import EpisodeRecord
from eval.agentbench.results_store import (
    build_dashboards,
    defect_gaps,
    read_parquet,
    render_html_dashboard,
    render_markdown_dashboard,
    success_matrix,
    write_parquet,
)


def _rec(task, defect, outcome, *, trial=0, excluded=None, tokens=30, cost=0.002):
    return EpisodeRecord(
        episode_id=f"tree|m|{task}|{defect}|t{trial}", task_id=task, app="miniwob",
        defect=defect, defect_family=(None if defect == "clean" else "name"),
        agent="tree", provider="fake", model="m", trial=trial,
        outcome=outcome, excluded_reason=excluded,
        input_tokens=tokens, output_tokens=0, cost_usd=cost,
    )


def _dataset():
    # Two tasks × two trials, clean succeeds, defect fails — a clean effect.
    recs = []
    for task in ("click-button", "click-link"):
        for trial in (0, 1):
            recs.append(_rec(task, "clean", "success", trial=trial))
            recs.append(_rec(task, "strip_name", "failure", trial=trial))
    # One excluded defect episode (does not count toward the rate).
    recs.append(_rec("click-button", "strip_name", "failure", trial=2, excluded="provider_error"))
    return recs


def test_parquet_round_trip_is_lossless(tmp_path):
    recs = _dataset()
    path = write_parquet(recs, tmp_path / "r.parquet")
    back = read_parquet(path)
    assert len(back) == len(recs)
    assert [r.model_dump() for r in back] == [r.model_dump() for r in recs]


def test_success_matrix_counts_usable_and_excluded():
    rows = {(c.agent, c.model, c.defect): c for c in success_matrix(_dataset())}
    clean = rows[("tree", "m", "clean")]
    assert clean.usable == 4 and clean.successes == 4 and clean.rate == 1.0
    defect = rows[("tree", "m", "strip_name")]
    # 5 defect episodes, 1 excluded -> 4 usable, all failures.
    assert defect.episodes == 5 and defect.excluded == 1
    assert defect.usable == 4 and defect.successes == 0 and defect.rate == 0.0


def test_matrix_puts_clean_first_in_each_block():
    rows = success_matrix(_dataset())
    assert rows[0].defect == "clean"  # clean sorts before defects within a block


def test_defect_gaps_use_the_paired_analysis():
    gaps = defect_gaps(_dataset())
    assert len(gaps) == 1
    g = gaps[0]
    assert g["defect"] == "strip_name"
    # Clean 100% vs defect 0% over 4 pairs -> +100% effect, the excluded pair dropped.
    assert g["pairs"] == 4 and g["diff"] == 1.0
    assert g["b_clean_only"] == 4 and g["c_defect_only"] == 0


def test_markdown_dashboard_renders():
    md = render_markdown_dashboard(_dataset())
    assert "Success by agent" in md
    assert "Clean vs defect" in md
    assert "strip_name" in md


def test_html_dashboard_is_self_contained():
    out = render_html_dashboard(_dataset())
    assert out.startswith("<!doctype html>")
    assert "prefers-color-scheme: dark" in out  # theme-aware
    assert "http://" not in out and "https://" not in out  # no network


def test_build_dashboards_writes_all_three(tmp_path):
    recs = _dataset()
    records_path = tmp_path / "records.jsonl"
    records_path.write_text("\n".join(r.model_dump_json() for r in recs), encoding="utf-8")
    built = build_dashboards(records_path, tmp_path / "dash")
    assert built["episodes"] == len(recs)
    assert built["parquet"].exists() and built["markdown"].exists() and built["html"].exists()
