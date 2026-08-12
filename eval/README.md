# eval/

The evaluation harness: synthetic defect injection and the precision
metrics measured against it. This is what turns "we think it works"
into a reproducible number — see the project plan's Phase 4 goal:
*prove the claims to a stranger who doesn't trust you.*

- [`inject/`](inject/) — fault injector scripts. Each one applies a
  single, reversible, known defect to a clean fixture.
- [`baselines/`](baselines/) — frozen accuracy metrics per Verity
  version, so a regression shows up as a diff against a committed
  number, not a vibe.
