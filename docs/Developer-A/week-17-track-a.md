# Nikhil — Week 17 Track A is in (scale: bounded crawl, cache, budget, auth, image)

**From Rohan.** Built and unit-tested without a browser or network. This is the
machinery your Readiness Report (B17.1′ site-list scan, B17.2′ sampled agent
tasks) runs on top of — it makes the scan bounded, cheap, and safe.

## What landed

| # | What | Where |
|---|---|---|
| A17.1 | **Bounded crawl frontier** — enforces every limit (pages, depth, same-origin, include/exclude) before a URL is visited; normalises URLs so dedup is real | `verity/crawl/frontier.py` |
| A17.1 | **Content-addressed findings cache** — keyed by (content hash, ruleset version, viewport); unchanged page states skipped | `verity/crawl/cache.py` |
| A17.1 | **Docker image** — Python + Node + Chromium in one image; entrypoint is the CLI | `deploy/Dockerfile` |
| A17.2 | **Authenticated crawling** — storage state by path, never inlined/committed; secret scrubbing for traces | `verity/crawl/auth.py` |
| A17.3 | **Crawl budget** — hard page/time/spend gate; a 25-page audit stops cleanly instead of overrunning CI | `verity/crawl/budget.py` |
| — | **Site crawl orchestrator** — frontier + cache + budget in one loop | `verity/crawl/site.py` |

## The interface your readiness scan calls

```python
from verity.crawl import crawl_site, CrawlBounds, CrawlBudget, FindingsCache

report = crawl_site(
    seeds=["https://site.example/"],
    render_fn=render,      # url -> RenderResult(content_hash, links)   (cheap: render + hash + links)
    analyze_fn=analyze,    # url -> findings                           (expensive: skipped on a cache hit)
    bounds=CrawlBounds(max_pages=25, max_depth=3, same_origin=True),
    budget=CrawlBudget(max_pages=25, max_seconds=600),
    cache=FindingsCache(Path(".verity/cache/findings")),
    ruleset_version="1.0.0", viewport="desktop",
)
report.pages_scanned, report.pages_from_cache, report.total_findings, report.budget_stopped
```

The two steps are split on purpose: `render_fn` is cheap and always runs (we
need the content hash to key the cache); `analyze_fn` is the expensive
accessibility pass and is **skipped entirely** when the cache already has
findings for that (content hash, ruleset, viewport). So an unchanged re-run over
a site does zero analysis — tested.

Wire `render_fn`/`analyze_fn` to the orchestrator's `scan_url` internals (render
→ hash + links; analyze → findings). I kept them injected so the crawl logic is
tested with in-memory fakes; the real wiring is a thin adapter.

## The invalidation set (please double-check — this is the correctness bug risk)

The cache key is **(content_hash, ruleset_version, viewport)** and nothing else.
That is the Week-17 artifact's whole point: a missed invalidation serves stale
findings. If the analysis depends on anything else that can change findings on
identical content (a config flag, a waiver set, a model/ruleset sub-version),
tell me and it goes in `CacheKey` — independently list what you think belongs
there, then we reconcile, per the artifact.

## Auth safety (A17.2)

`AuthConfig(storage_state_path=…)` takes a **path**; it raises `CredentialLeak`
if you hand it an inline JSON blob (that's how a credential gets committed).
`load_storage_state` warns if the file is inside the repo. `scrub_secrets(text,
values)` redacts secret values from any trace/log line (longest-first). Pass the
same value set to your screenshot pipeline so credentials never reach an
artifact.

## Not built here
The Docker image isn't built in CI (no Docker in the test env) — it's a standard
two-toolchain image on the Playwright Python base; build it with
`docker build -f deploy/Dockerfile -t verity:local .`. Tell me if you want a CI
job that builds and smoke-tests it.
