# eval/corpus/ — Spike A labelled corpus (A2.3)

Labelled good/bad HTML pairs for measuring precision. Each pair is a
clean source page and a copy with exactly one known defect injected, so
the ground truth is perfect: we know the defect, its location, and its
success criterion because we introduced it.

## Regenerate

```bash
cd ~/Desktop/verity
uv run python -m eval.corpus.build       # fetch (cached) + generate
uv run python -m eval.corpus.verify      # rendered check — slow, optional
```

The corpus is **version-controlled by manifest, not by committed
binaries** (A2.3's acceptance). Tracked: `sources.yaml` and the two
scripts. Ignored: `.cache/` (fetched pages) and `generated/` (the
corpus itself). `build.py --offline` rebuilds from cache without a
network round trip; the output is byte-identical across runs.

## What's in it

~30 source pages (W3C ARIA APG examples + the Before/After Demo
"after" set — deliberately accessible starting points) crossed with the
three Week 1 injectors, one defect per case:

| Injector | Success criterion | Defect |
|---|---|---|
| `strip_alt` | 1.1.1 | removes `alt` from one image |
| `detach_label` | 1.3.1 | points one `<label for>` at a dead id |
| `reduce_contrast` | 1.4.3 | forces `#ccc` on `#fff` on one text node |

The mix skews toward contrast and alt-text, which matches the real
prevalence WebAIM reports for those two failure types.

`generated/labels.json` is the index: every case with its paths, the
expected SC and outcome, content hashes of both halves, and the
structural verification result.

## Two layers of verification

Ground truth that is silently wrong makes every downstream precision
number wrong, and the corruption is invisible without an explicit
check. So there are two:

1. **Structural** (`build.py`, always) — asserts the injection changed
   exactly one element and only the attribute it was supposed to. A
   transform that alters something else is rejected, not shipped.

2. **Rendered** (`verify.py`, opt-in) — renders both halves through the
   real worker and keeps the `fail` label only if the defect actually
   *manifests* as a new finding of the expected criterion.

The second layer exists because structural correctness is not enough. A
missing-label defect injected into a **hidden accordion panel** changes
the DOM correctly yet produces no accessibility barrier — a hidden
element has none — so axe correctly reports nothing. Structurally it's a
valid injection; as ground truth it's a false positive waiting to
happen. `verify.py` downgrades those cases to
`expected_outcome: "no_manifest"` rather than deleting them, so the
reason stays inspectable.

The rendered check is sound *for this corpus* because all three Week 1
injectors target deterministically-detectable criteria. It would be
wrong for the vision-only injectors added later (contrast-over-image,
alt-meaningfulness) — those are precisely the cases axe declines to
judge — so the check stays scoped to the deterministic set.

## For Spike A

This is the labelled data the Week 2 precision gate measures against.
The vision model's alt-meaningfulness and focus-visible judgments are
scored on the `detected` cases here; without labelled data there is no
precision to measure, which is why the injectors had to ship in Week 1.
