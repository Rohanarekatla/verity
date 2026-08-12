# eval/inject/

Fault injectors: reversible DOM transforms that take a clean fixture
and apply exactly one known defect, so the eval harness has labelled
ground truth to measure precision/recall against.

Planned, not yet implemented:

- `strip_alt.py` — removes `alt` text from an image
- `detach_label.py` — breaks a `<label>`/control association
- `reduce_contrast.py` — drops text contrast below 4.5:1

Each injector needs a verification pass confirming it created exactly
the intended defect and nothing else — an injector that accidentally
masks a second issue silently corrupts every downstream metric.
