# verity/calibration/

Turns raw model confidence into calibrated probabilities, since a raw
model score isn't one.

Planned, not yet implemented:

- `isotonic.py` — isotonic regression mapping raw signals to
  calibrated probabilities, fit on a held-out injected split
- `conformal.py` — conformal prediction; a non-singleton prediction
  set becomes `needs_review` rather than a false-confidence verdict
