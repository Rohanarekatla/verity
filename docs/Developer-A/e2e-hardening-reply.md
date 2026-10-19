# Rohan — reply to your E2E hardening notes (18 Oct)

**From Nikhil.** Re: `docs/Developer-B/e2e-hardening-changes-in-your-files.md`
and `docs/measurements/e2e-hardening-2026-10-18.md`.

## Your four changes to my files — all accepted as-is

| File | Your change | Verdict |
|---|---|---|
| `agents/keyboard.py` | `tabindex is None` = attribute absent, not "unknown" | Correct — that was my bug; it contradicted the TabStop docstring |
| `agents/contrast.py` | `text_pixel_count == 0` → `cantTell` (no glyphs found) | Correct. I also checked `text_size_class` at every WCAG boundary (18px bold, 18.667px w600, 23.99px) — all right |
| `cli.py` | exit 2 for crashes, 120s timeout, `normalize_target` for local files | Correct |
| `orchestrator/main.py` | `_run_apg_contracts` (Step 3.8) | Correct; one hardening added, below |

## Two things I fixed on top, found while reviewing

1. **A broken `waivers.yaml` exited 1, not 2.** `report_expired_waivers`
   returned the parse error as if it were an expired waiver, so CI would have
   said "the site has gating failures" when the real problem was our config.
   It now prints `WAIVER FILE INVALID` and re-raises → exit 2. It was only
   unreachable today by accident of call order.
   Test: `test_waivers.py::test_broken_waiver_file_exits_2_not_1`.
2. **A bug in `interaction.to_findings` could take down the whole scan.**
   It ran outside the try/except that protects the APG stage. Now a mapping
   failure logs a WARNING and drops only the interaction findings; axe,
   contrast and keyboard findings still ship.
   Test: `test_main.py::test_a_defect_in_one_agent_does_not_take_down_the_whole_scan`.

## B7.4 — done (your "not done here: gating on new findings only")

Consumes your A7.2 `baseline.py` unchanged. New:
`verity/report/regression.py`, `--baseline PATH` on `verity scan`, tests in
`verity/tests/test_regression.py`.

```
verity scan ./dist/index.html --write-baseline .verity/baseline.json   # record once
verity scan ./dist/index.html --baseline .verity/baseline.json          # gate on new only
```

- Only findings **absent from the baseline** can gate, and of those only what
  the `ci:` policy gates on (default authoritative). Week 7 gate: 50 old + 1
  new fails on exactly the 1. Week 8 gate: a new AI-assisted finding shows in
  the diff but does not fail the build. Both are tests.
- **Keyed to `ruleset_version` + corpus hash.** I read "corpus hash" as the
  baseline's content address (`baseline_id`) — the hash of the accepted
  finding set it was computed against. The log line names both. **If you meant
  something else by "corpus hash" (e.g. a hash of the scanned pages), tell me
  and I'll change the key.**
- **Mismatch is refused, exit 2:** different `ruleset_version`, or different
  validator major (your `version_mismatch`). New rules produce findings nobody
  in the PR introduced; gating on them is the uninstall scenario. Fix = re-record
  (your A8.3 workflow). A missing or hand-edited baseline file also exits 2,
  and is checked *before* the render.
- **Target is not in the key** — only a warning — because a local file has a
  different `file://` URI on a laptop vs CI.
- For A8.1: the Action can pass `--baseline` through when the repo has one.

## Your question: "is 'APG-only ⇒ warning' the line you'd draw too?"

**Yes.** Verity gates on WCAG, and APG is how we know what to test, not the
bar. It also fits ADR-0004: an APG-only failure becomes `NEEDS_REVIEW` /
`cantTell` in `to_findings`, so it is shown and never gates.

One condition: a check may tag a result `APG_ONLY` **only when the WCAG
requirement behind it is independently met.** Example: "every tab is in the
Tab order" is APG-only *because* every tab is still reachable. If any tab is
**not** reachable, that is a 2.1.1 failure and must stay a `violation`. Worth
a fixture that pins this.

## Not mine / still open from your report

- SARIF `startLine` always 1, and shadow-DOM / iframe blind spots — noted.
  Shadow-DOM accname (B9.3) now comes from the browser's computed name.
- Week 9 Track B is done too — see [`week-9-track-b.md`](week-9-track-b.md).
