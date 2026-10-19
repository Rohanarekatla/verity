# Nikhil — end-to-end hardening touched four of your files

**From Rohan.** Full report: `docs/measurements/e2e-hardening-2026-10-18.md`.
Each change below fixes a false verdict or a crash found on real sites; none
changes a doctrine you wrote — mostly they make the code match it. Please
review these specifically.

## `verity/agents/keyboard.py` — SC 2.4.3

Removed the "tabindex was not recorded → indeterminate" branch. Under the
TabStop contract we agreed (and `traverse.ts` implements), `tabindex: None`
means the attribute is **absent** — a plain `<button>`. The branch made 2.4.3
needs-review on every real page (gov.uk: "176 stops not recorded"). The test
`test_unrecorded_tabindex_is_indeterminate` became
`test_absent_tabindex_is_not_unknown`.

## `verity/agents/contrast.py`

New first check: `text_pixel_count == 0` → `cantTell`
(`foreground-not-found-in-pixels`). If no rendered pixel matches the text
colour, the colour is not what the glyphs are painted in. The
`sampling-failed` message no longer blames only animation/video.

## `verity/cli.py`

- Exit **2** when the scan cannot complete (was 1 — indistinguishable from
  "gating findings" in CI). The Action reports exit 2 as "could not complete".
- Default `--timeout` 30 s → 120 s (real pages legitimately take longer).
- `verity scan ./dist/index.html` works (files only, not directories).

## `verity/orchestrator/main.py`

`_run_apg_contracts` wired in as Step 3.8, after your BC-A1 traversal — it
presses keys, so it must be last. Same graceful fallback as yours. This was
on your list in `week-9-contract-runner.md`; I did it because end-to-end
testing showed the click-only disclosure exiting 0.

## Your `tablist.yaml` — semantics, not text

Assertions are unchanged; the runner now reports some failures at **warning**
severity when they break the APG pattern but are not WCAG barriers:
all-tabbable tabs (`roving-tabindex`), Tab moving to the next tab
(`tab-moves-out-of-the-tablist`), arrows not moving when every tab is
tabbable, and missing `aria-controls`. They are still reported — they just
cannot gate. The fail fixture is now a real barrier (roving tabindex with no
arrow keys). I'd value your view at the pair session: is "APG-only ⇒ warning"
the line you'd draw too?
