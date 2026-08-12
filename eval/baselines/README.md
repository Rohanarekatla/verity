# eval/baselines/

Frozen accuracy metrics per Verity version (e.g. `0.1.0.json`) —
precision/recall/FP-rate on the fixture corpus at that point in time.
CI compares new results against the frozen baseline; a drop fails the
build once a baseline has been committed.

Not yet populated — no baseline exists until the eval harness in
[`eval/inject/`](../inject/) produces its first real numbers.
