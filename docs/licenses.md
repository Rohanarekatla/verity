# Licence ledger (S19.1) — verified, not assumed

**Checked 2026-10-30** by reading each package's actual licence file in the
installed environment (`.venv/Lib/site-packages/*.dist-info/licenses/`,
`node-worker/node_modules/*/LICENSE`), not its metadata alone. Anything that
could not be read here is marked **UNVERIFIED** and must be checked by a person
before release. Re-run this check whenever a dependency is added or bumped.

Verity itself: **MPL-2.0** (`LICENSE`).

## Python (runtime + test)

| Package | Version | Licence (from the licence file) | Verified |
|---|---|---|---|
| pydantic | 2.13.4 | MIT | yes |
| pydantic-core | 2.46.4 | MIT | yes |
| annotated-types | 0.8.0 | MIT | yes |
| typing-extensions | 4.16.0 | PSF-2.0 | yes |
| typing-inspection | 0.4.3 | MIT | yes |
| pyyaml | 6.0.3 | MIT | yes |
| beautifulsoup4 | 4.15.0 | MIT | yes |
| soupsieve | 2.9.2 | MIT | yes |
| pyarrow | 26.0.0 | Apache-2.0 | yes |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | yes |
| colorama | 0.4.6 | BSD (3-clause text) | yes |
| pygments | 2.20.0 | BSD-2-Clause | yes |
| pytest | 9.1.1 | MIT | yes |
| pytest-asyncio | 1.4.0 | Apache-2.0 | yes |
| pluggy | 1.6.0 | MIT | yes |
| iniconfig | 2.3.0 | MIT | yes |

Optional, not installed in this environment (imported lazily; **UNVERIFIED**
here): `playwright` (Python, used by the agent benchmark env — Apache-2.0 per
upstream), `mlx-vlm` (vision experiment, flag-gated).

## Node worker

| Package | Version | Licence | Verified |
|---|---|---|---|
| axe-core | 4.13.0 | MPL-2.0 (+ `LICENSE-3RD-PARTY.txt` shipped with it) | yes |
| playwright | 1.62.1 | Apache-2.0 | yes |
| playwright-core | 1.62.1 | Apache-2.0 | yes |
| typescript | 7.0.2 | Apache-2.0 | yes (dev) |
| @typescript/typescript-win32-x64 | 7.0.2 | Apache-2.0 | yes (dev) |
| @types/node | 26.2.0 | MIT | yes (dev) |
| undici-types | 8.3.0 | MIT | yes (dev) |

**Chromium** (downloaded by Playwright at install): BSD-3-Clause plus the
third-party notices Chromium ships — **UNVERIFIED** in this repo; read
`about:credits` in the downloaded build before release.

## Benchmark and data

| Item | Licence | Verified |
|---|---|---|
| MiniWoB++ (vendored at run time, not committed; `eval/agentbench/vendor/`) | MIT per the Farama Foundation repository | **UNVERIFIED** here (not present in this checkout) — read its LICENSE when vendoring |
| W3C APG examples (fetched by `eval/apg_reference_check.py`, not redistributed) | W3C Software and Document License | **UNVERIFIED** — we only fetch, never ship them |
| WebAIM Million 2026 figures (cited in the pre-registration) | cited statistics, no redistribution | n/a |
| Our fixtures, contracts, injectors | MPL-2.0 (this repo) | yes |

## Models and providers (plan v2: "checked for every model used in published results")

| Model / provider | Use | Terms | Verified |
|---|---|---|---|
| Qwen3-8B / Qwen3-14B (Ollama) | benchmark bulk runs | Apache-2.0 per the model cards | **UNVERIFIED** — read the model card licence of the exact weights pulled, record the digest here |
| Qwen2.5-VL-7B (vision experiment, flag-gated) | not used in published results | Apache-2.0 per model card | **UNVERIFIED** |
| Anthropic API (Claude) | frontier runs, fix loop | Anthropic Commercial Terms | **UNVERIFIED** — a person must confirm benchmark publication is permitted |
| OpenAI API | optional frontier runs | OpenAI Services Agreement | **UNVERIFIED** — same |

Release blocker: every **UNVERIFIED** row that is actually used in the release
or the published results must be verified and dated here first.
