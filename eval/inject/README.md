# eval/inject/

Fault injectors: reversible DOM transforms that take a clean fixture
and apply exactly one known defect, so the eval harness has labelled
ground truth to measure precision/recall against.

Implemented (B1.5):

- `strip_alt.py` — removes `alt` from images
- `detach_label.py` — points `<label for>` at a nonexistent id
- `reduce_contrast.py` — forces `#cccccc` on `#ffffff` (≈1.6:1)

Each has an `inject(html, selector)` / `revert(html, selector)` pair.
The original value is stashed in a `data-verity-original-*` attribute
so the transform is reversible.

## The verification pass

B1.5's acceptance criterion has two halves: assert the defect **was
introduced**, *and* that **no unintended second defect appeared**.

The second half is the one that matters most and the one easiest to
skip. Injecting a defect can accidentally mask or create another, and
ground truth that is silently wrong makes every downstream number
wrong — invisibly. `verity/tests/test_injectors.py` covers this
structurally: each injector is asserted to add and remove exactly the
attributes it claims, on exactly the elements it selected, leaving
every other element byte-identical.

Verified end-to-end against a real browser as well: injecting
`reduce_contrast` into `data/fixtures/contrast-pass.html` adds exactly
one axe violation (`color-contrast` on the targeted selector) and masks
none of the pre-existing ones.

Week 14 (**A14.2**) turns this into a corpus-wide verification pass
that aborts corpus generation with a diagnostic when it fails.

## Known issue — revert is not byte-identical

`revert(inject(html))` is *semantically* identical to the input but not
*textually* identical: BeautifulSoup re-serialises on the way through,
normalising `<!doctype html>` → `<!DOCTYPE html>`, collapsing
indentation, and rewriting `<meta ... />` → `<meta .../>`.

Why it matters: a paired good/bad corpus should differ by **the defect
and nothing else**. If the "bad" half is `inject(clean)` while the
"good" half is the original file, the pair differs by the defect *plus*
whitespace. That noise is harmless for axe (which parses, not diffs)
but it makes any text-level diff of the pair unreadable, and it means
regenerating the corpus produces a different baseline than the files
already on disk.

**Open decision (ADR candidate), two workable options:**

1. **Normalise both halves.** Generate the "good" fixture by running
   the clean source through the same BeautifulSoup round-trip, so both
   halves share a serialisation. Cheapest, and makes the pair a true
   one-defect diff.
2. **Preserve formatting.** Use a formatting-preserving parser or apply
   edits textually. More faithful, materially more work.

Option 1 is the recommendation unless the corpus needs to keep the
exact bytes of real-world source pages.

Not affected: `finding_signature` (W7/A7.1) is explicitly required to
survive reformatting, so signature stability does not depend on this.
