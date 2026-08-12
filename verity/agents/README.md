# verity/agents/

ML workers and verification agents that turn raw signals into
findings.

Planned, not yet implemented:

- `contrast.py` — adjudicates axe's `incomplete` contrast findings
  over rendered images
- `vision.py` — VLM-based visual reasoning (alt-text judgment, etc.)
- `audio.py` — screen-reader announcement prediction
- [`validator/`](validator/) — dedup, provenance stamping, severity
  assignment — the last stop before a finding is reported

The rule that governs all of these: the model *localises*, deterministic
math *decides*. A finding's verdict should never rest solely on a
number a model produced.
