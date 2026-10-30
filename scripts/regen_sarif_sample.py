#!/usr/bin/env python
"""
Regenerate the committed sample SARIF, eval/fixtures/minimal.sarif.json.

This is the ONLY thing that writes the tracked fixture — the test suite never
does (it builds into a tmp dir and only *checks* the committed copy). Run this
deliberately when the SARIF format or the sample's findings change, then commit
the result:

    python scripts/regen_sarif_sample.py

The sample is byte-stable across machines because its target is a fixed string
(verity.tests.test_report.SAMPLE_TARGET), so regenerating on any machine
produces the same file.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The project runs from the repo root (no installed package); put it on the path
# so this works as `python scripts/regen_sarif_sample.py` from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verity.tests.test_report import SAMPLE_PATH, build_sample_sarif  # noqa: E402


def main() -> int:
    out = build_sample_sarif(SAMPLE_PATH)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
