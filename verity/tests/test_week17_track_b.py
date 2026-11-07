"""Week 17, Track B — the Agent Readiness Report pipeline (B17.1′–B17.3′), without a browser or network."""

import json
from pathlib import Path

from eval.readiness_report import (
    PageRecord,
    SiteRecord,
    TaskRecord,
    analyze,
    load_site_records,
    load_sites,
    load_tasks,
    render_report,
    run_agent_tasks,
    run_scan,
    sample_sites,
    scan_site,
    svg_bars,
    svg_histogram,
    write_report,
)

REPO = Path(__file__).resolve().parents[2]


def page(url, score=80.0, named_earned=30.0, fails=None, tools=0):
    return PageRecord(url=url, content_hash=url, static_score=score, static_coverage=0.8,
                      points={"named_controls": {"earned": named_earned, "max": 30, "status": "measured"}},
                      fails_by_sc=fails or {}, webmcp_tools=tools)


def test_site_lists_accept_urls_domains_and_tranco_csv(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("# comment\nhttps://a.example/\nb.example\n1,c.example\nb.example\n", encoding="utf-8")
    assert load_sites(p) == ["https://a.example/", "https://b.example/", "https://c.example/"]
    assert len(load_sites(REPO / "data" / "readiness" / "sites-sample.txt")) == 8


def test_the_agent_sample_is_seeded_not_hand_picked():
    sites = [f"https://s{i}.example/" for i in range(50)]
    assert sample_sites(sites, 5) == sample_sites(list(reversed(sites)), 5)
    assert len(sample_sites(sites, 5)) == 5 and len(sample_sites(sites[:3], 5)) == 3


def test_scan_site_crawls_within_bounds_and_survives_a_broken_page():
    def page_fn(url):
        if url.endswith("/broken"):
            raise TimeoutError("navigation timeout")
        return page(url), ["https://s.example/a", "https://s.example/broken", "https://other.example/x"]

    rec = scan_site("https://s.example/", max_pages=3, max_depth=1, page_fn=page_fn)
    urls = {p.url for p in rec.pages}
    assert "https://s.example/" in urls and "https://s.example/a" in urls
    assert "https://other.example/x" not in urls, "same-origin bound"
    assert "https://s.example/broken" in rec.render_failed


def test_run_scan_is_resumable_and_a_failing_site_is_recorded(tmp_path):
    calls = []

    def scan_fn(site):
        calls.append(site)
        if "bad" in site:
            raise RuntimeError("DNS failure")
        return SiteRecord(site=site, pages=[page(site)])

    sites = ["https://ok.example/", "https://bad.example/"]
    path = run_scan(sites, tmp_path, scan_fn=scan_fn)
    run_scan(sites, tmp_path, scan_fn=scan_fn)
    assert calls == sites, "the second run skips sites already recorded"
    recs = load_site_records(path)
    assert recs[1].error and "DNS failure" in recs[1].error and recs[0].score == 80.0


def test_agent_stage_stops_cleanly_at_the_budget_and_resumes(tmp_path):
    from eval.agentbench.providers import BudgetExceeded

    tasks = {"*": [{"task": "search"}, {"task": "menu"}]}
    seen = []

    def task_fn(site, t):
        seen.append((site, t["task"]))
        if len(seen) == 2:
            raise BudgetExceeded(1.0, 0.5, 1.0)
        return TaskRecord(site=site, task=t["task"], verdict="passed", succeeded=True)

    path = run_agent_tasks(["https://a.example/"], tasks, tmp_path, task_fn=task_fn)
    assert len(path.read_text().splitlines()) == 1, "budget stop keeps what ran, writes nothing for the refused one"
    run_agent_tasks(["https://a.example/"], tasks, tmp_path,
                    task_fn=lambda s, t: TaskRecord(site=s, task=t["task"], verdict="failed", succeeded=False))
    assert len(path.read_text().splitlines()) == 2


def test_tasks_file_parses():
    tasks = load_tasks(REPO / "data" / "readiness" / "tasks-sample.yaml")
    assert "*" in tasks and all("task" in t for t in tasks["*"])


def test_analysis_attributes_only_confirmed_failures_to_sites():
    sites = [SiteRecord("https://a/", pages=[page("https://a/", 90, fails={"4.1.2": 2}, tools=1)]),
             SiteRecord("https://b/", pages=[page("https://b/", 50, named_earned=15, fails={"4.1.2": 1, "1.4.3": 1})]),
             SiteRecord("https://c/", error="DNS")]
    tasks = [TaskRecord("https://a/", "t1", "passed", True),
             TaskRecord("https://b/", "t1", "failed", False, confirmed=True, sc="4.1.2"),
             TaskRecord("https://b/", "t2", "infeasible", False, confirmed=False),
             TaskRecord("https://b/", "t3", "error", False, error="x")]
    s = analyze(sites, tasks)
    assert s["sites_scanned"] == 2 and s["sites_failed"] == ["https://c/"]
    assert s["score_median"] == 70 and s["share_sites_with_unnamed_controls"] == 0.5
    assert s["share_sites_declaring_webmcp"] == 0.5
    assert s["top_failing_sc"][0] == ("4.1.2", 2)
    t = s["tasks"]
    assert (t["run"], t["errors"], t["failed_confirmed"], t["failed_unconfirmed"]) == (3, 1, 1, 1)
    md = render_report(s)
    assert "Only confirmed failures are attributed to the site." in md and "70/100" in md


def test_figures_are_accessible_svg():
    h = svg_histogram([10, 55, 56, 90], title="Scores")
    assert 'role="img"' in h and "<title id=\"t\">Scores</title>" in h and "50–60: 2" in h
    b = svg_bars([("4.1.2", 3.0), ("1.4.3", 1.0)], title="SC")
    assert "4.1.2: 3" in b


def test_write_report_end_to_end_from_jsonl(tmp_path):
    from dataclasses import asdict

    (tmp_path / "sites.jsonl").write_text(
        json.dumps(asdict(SiteRecord("https://a/", pages=[page("https://a/")]))) + "\n", encoding="utf-8")
    path = write_report(tmp_path)
    assert path.read_text().startswith("# Agent Readiness Report")
    assert (tmp_path / "figures" / "scores.svg").exists() and (tmp_path / "stats.json").exists()
