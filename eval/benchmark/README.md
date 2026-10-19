# eval/benchmark — Verity vs the field

`benchmark.py` runs Verity, axe-core, Lighthouse, Pa11y and IBM Equal Access
on the same pages with **known answers** and scores each against the truth.
Latest results: [`docs/measurements/benchmark-2026-10-19.md`](../../docs/measurements/benchmark-2026-10-19.md).

```bash
cd node-worker && npm run build && cd ..
uv run python eval/benchmark/benchmark.py              # all five tools
uv run python eval/benchmark/benchmark.py verity axe   # a subset
```

The first run installs pinned competitor versions into `work/`
(git-ignored), builds the page set there, and serves it on
`127.0.0.1:8765` for the duration of the run. Every tool uses the Chromium
that Playwright installed for the worker.

| File | Role |
|---|---|
| `benchmark.py` | builds pages + ground truth, runs the tools, scores, prints Markdown tables |
| `axe_run.mjs` | standalone axe-core, as a CI user would run it |
| `resolve.mjs` | maps every tool's selector / XPath to the real DOM element |

Fairness rules are in the docstring of `benchmark.py`. When a number looks
too good, check `work/raw.json` (every finding, every tool) before believing
it — that is how two scoring mistakes were caught while building this.
