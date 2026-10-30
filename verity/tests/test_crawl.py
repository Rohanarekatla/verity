"""
Week 17 Track A — bounded crawl, cache, budget, auth, site orchestration.

Proves every configured limit is enforced before a page is visited; the cache
invalidates on content, ruleset, and viewport (a missed one would serve stale
findings); the budget stops the crawl cleanly; credentials can't be inlined and
secrets are scrubbed; and a full crawl is bounded, cached across runs (an
unchanged second run does zero analysis), and budget-stoppable.
"""

import pytest

from verity.crawl.auth import AuthConfig, CredentialLeak, load_storage_state, scrub_secrets
from verity.crawl.budget import BudgetExceeded, CrawlBudget
from verity.crawl.cache import CacheKey, FindingsCache
from verity.crawl.frontier import CrawlBounds, CrawlFrontier, normalize_url
from verity.crawl.site import RenderResult, crawl_site


# --- frontier --------------------------------------------------------------

def test_normalize_url_collapses_equivalents():
    base = normalize_url("https://Example.com/a/")
    assert normalize_url("https://example.com/a") == base
    assert normalize_url("https://example.com/a#section") == base
    assert normalize_url("https://example.com/a?utm_source=x") == base
    assert normalize_url("https://example.com/a?id=7") != base  # a real param stays


def test_bounds_enforced():
    b = CrawlBounds(max_depth=2)
    origin = "https://site.com/"
    assert b.allowed("https://site.com/x", 1, origin)[0]
    assert not b.allowed("https://site.com/x", 3, origin)[0]          # too deep
    assert not b.allowed("https://other.com/x", 1, origin)[0]         # off-origin
    assert not b.allowed("https://site.com/logo.png", 1, origin)[0]   # excluded ext
    assert not b.allowed("ftp://site.com/x", 1, origin)[0]            # non-http


def test_frontier_dedupes_and_respects_page_budget():
    f = CrawlFrontier(origin="https://s.com/", bounds=CrawlBounds(max_pages=2, max_depth=5))
    assert f.add("https://s.com/a", 0) is True
    assert f.add("https://s.com/a/", 0) is False       # same normalised url
    assert f.add("https://s.com/b", 0) is True
    assert f.add("https://s.com/c", 0) is False        # page budget hit
    assert "page budget" in f.skipped[normalize_url("https://s.com/c")]
    assert f.enqueued == 2


def test_frontier_resolves_relative_links():
    f = CrawlFrontier(origin="https://s.com/", bounds=CrawlBounds(max_pages=10))
    f.add("https://s.com/dir/page", 0)
    assert f.add("../other", 1, base="https://s.com/dir/page") is True


# --- cache -----------------------------------------------------------------

def test_cache_miss_then_hit(tmp_path):
    cache = FindingsCache(tmp_path)
    key = CacheKey(content_hash="abc", ruleset_version="1.0.0")
    assert cache.get(key) is None and cache.misses == 1
    cache.put(key, [{"id": "f1"}])
    assert cache.get(key) == [{"id": "f1"}] and cache.hits == 1


def test_cache_invalidates_on_ruleset_and_viewport(tmp_path):
    cache = FindingsCache(tmp_path)
    cache.put(CacheKey("abc", "1.0.0", "desktop"), [{"id": "x"}])
    assert cache.get(CacheKey("abc", "2.0.0", "desktop")) is None   # ruleset bump
    assert cache.get(CacheKey("abc", "1.0.0", "mobile")) is None    # viewport
    assert cache.get(CacheKey("def", "1.0.0", "desktop")) is None   # content


# --- budget ----------------------------------------------------------------

def test_budget_stops_on_pages():
    b = CrawlBudget(max_pages=2)
    b.start()
    b.ensure(); b.record()
    b.ensure(); b.record()
    with pytest.raises(BudgetExceeded):
        b.ensure()


def test_budget_stops_on_time():
    t = [100.0]
    b = CrawlBudget(max_pages=99, max_seconds=5, clock=lambda: t[0])
    b.start()
    b.ensure()               # elapsed 0
    t[0] = 106.0             # 6s later
    with pytest.raises(BudgetExceeded) as e:
        b.ensure()
    assert "time budget" in e.value.reason


# --- auth ------------------------------------------------------------------

def test_scrub_secrets_longest_first_and_ignores_blank():
    text = "token=SUPERSECRET123 and user=SUPER"
    out = scrub_secrets(text, ["SUPER", "SUPERSECRET123", "", "  "])
    assert "SUPERSECRET123" not in out and "«redacted»" in out
    assert out == "token=«redacted» and user=«redacted»"


def test_inline_credentials_are_refused():
    with pytest.raises(CredentialLeak):
        AuthConfig(storage_state_path='{"cookies": []}')   # a blob, not a path


def test_load_storage_state_reads_path(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    state = load_storage_state(str(p), repo_root=tmp_path)   # inside -> warns, still loads
    assert state == {"cookies": [], "origins": []}
    with pytest.raises(FileNotFoundError):
        load_storage_state(str(tmp_path / "missing.json"))


# --- site orchestration ----------------------------------------------------

def _graph_render(links_by_url):
    def render(url):
        return RenderResult(content_hash="h:" + url, links=links_by_url.get(url, []))
    return render


def test_crawl_respects_page_cap_and_follows_links():
    links = {
        "https://s.com/": ["https://s.com/a", "https://s.com/b"],
        "https://s.com/a": ["https://s.com/c", "https://s.com/d"],
    }
    analyzed = []
    report = crawl_site(
        ["https://s.com/"],
        render_fn=_graph_render(links),
        analyze_fn=lambda url: analyzed.append(url) or [{"id": url}],
        bounds=CrawlBounds(max_pages=3, max_depth=5),
    )
    assert report.pages_scanned == 3 and len(analyzed) == 3   # capped, links followed


def test_crawl_skips_off_origin_links():
    links = {"https://s.com/": ["https://s.com/a", "https://off.com/x"]}
    report = crawl_site(
        ["https://s.com/"],
        render_fn=_graph_render(links),
        analyze_fn=lambda url: [{"id": url}],
        bounds=CrawlBounds(max_pages=10, max_depth=5),   # budget not the limit here
    )
    assert "https://off.com/x" not in [p.url for p in report.pages]
    assert any("off-origin" in r for r in report.skipped.values())


def test_cache_skips_analysis_on_unchanged_second_run(tmp_path):
    links = {"https://s.com/": ["https://s.com/a"]}
    cache = FindingsCache(tmp_path)
    calls = {"n": 0}

    def analyze(url):
        calls["n"] += 1
        return [{"id": url}]

    kw = dict(render_fn=_graph_render(links), analyze_fn=analyze,
              bounds=CrawlBounds(max_pages=5), cache=cache)
    first = crawl_site(["https://s.com/"], **kw)
    assert first.pages_from_cache == 0 and calls["n"] == 2   # analysed both pages
    second = crawl_site(["https://s.com/"], **kw)
    assert second.pages_from_cache == 2 and calls["n"] == 2   # no new analysis
    assert second.pages_scanned == 2


def test_crawl_budget_stop_is_reported():
    links = {"https://s.com/": ["https://s.com/a", "https://s.com/b"]}
    report = crawl_site(
        ["https://s.com/"],
        render_fn=_graph_render(links),
        analyze_fn=lambda url: [],
        bounds=CrawlBounds(max_pages=10),
        budget=CrawlBudget(max_pages=1),
    )
    assert report.budget_stopped and report.pages_scanned == 1
    assert "<budget>" in report.skipped
