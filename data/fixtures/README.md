# data/fixtures/

Paired good/bad HTML test files — a clean widget and a version with a
specific, known defect injected. Used by both the Node worker's tests
and the Python fault-injection harness in [`eval/`](../../eval/) so
the two sides test against the same ground truth.

- `contrast-fail.html` / `contrast-pass.html` — a paragraph at ~1.6:1
  contrast (fails WCAG AA 4.5:1) and the same paragraph at ~12.6:1
  (passes). Exercised by
  [`node-worker/test/render-axe.test.mjs`](../../node-worker/test/render-axe.test.mjs)
  to prove `render` → `runAxe` produces one correct finding on the bad
  page and zero false positives on the good one.
