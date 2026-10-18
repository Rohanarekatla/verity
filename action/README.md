# action/ — Verity GitHub Action (A8.1–A8.3)

A composite Action that runs Verity in CI and surfaces findings as inline PR
annotations through GitHub code scanning. This is "the first useful thing" —
the surface a stranger judges the project by.

## The scan-target decision (why `target`, not `url`, by default)

**Verity scans a URL; SARIF annotates a file.** An inline PR annotation needs a
repo-relative path and a line number; a finding on
`https://staging.example.com/pricing` has neither. So the Action defaults to
scanning a **local built HTML file from the checkout** (`target:`), which maps
to a real path and annotates inline. Scanning a **remote URL** (`url:`) is a
separate mode — findings appear in the Security tab only, never inline. The
full reasoning is in [`../docs/sarif-reference.md`](../docs/sarif-reference.md)
§5, and it was taken jointly (ADR discussion, Week 8).

## Usage

```yaml
# .github/workflows/accessibility.yml in a consuming repo
name: Accessibility
on: pull_request
permissions:
  contents: read
  security-events: write   # required to upload SARIF to code scanning
jobs:
  verity:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Rohanarekatla/verity/action@main
        with:
          target: dist/index.html        # a built file in the checkout
          # config: verity.yml            # optional ci: { fail_on, annotate_on }
```

Inline annotations require **code scanning** enabled on the repo and the
`security-events: write` permission shown above. With neither, findings still
run and the build still gates — they just don't appear inline.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `target` | — | Repo-relative path to a built HTML file (default mode; annotatable) |
| `url` | — | Remote URL to scan instead (Security-tab only). Mutually exclusive with `target` |
| `config` | — | Config file with a `ci: { fail_on, annotate_on }` block |
| `sarif-file` | `verity-results.sarif` | Where to write SARIF |
| `upload-sarif` | `true` | Upload to code scanning |
| `write-baseline` | — | Record findings to a baseline instead of gating (used by the baseline workflow) |

## Caching (A8.2)

The Action caches the Playwright Chromium download (keyed on the worker
lockfile) and the vision model directory, so repeat runs don't re-fetch
~150 MB of browser or several GB of model. Vision is descoped to an experiment
(ADR-0002) and off by default, so a normal run never populates the model cache.

## Baseline workflow (A8.3)

[`../.github/workflows/verity-baseline.yml`](../.github/workflows/verity-baseline.yml)
regenerates the baseline and opens a **PR** with the result — manually
triggered, never automatic. Accepting a new set of findings as "known" is a
human decision; a self-updating baseline would silently absorb regressions.
The gating half (fail only on findings *new* since the baseline) is B7.4, which
consumes `verity/report/baseline.py`'s `diff_report`.

## Not verifiable from here

Confirming an annotation actually renders inline needs a PR against a repo with
code scanning enabled (see `../docs/sarif-reference.md` §6). The Action's shape
is built to that contract; the live confirmation is the one step that needs a
real repo.
