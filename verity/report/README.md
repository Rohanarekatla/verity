# verity/report/

Output generators — turning `AuditReport` into formats other tools and
people can consume.

Planned, not yet implemented:

- `sarif.py` — SARIF 2.1.0, for GitHub PR annotations
- `acr.py` — VPAT 2.5 ACR draft documents; every AI-assisted row is
  labelled "requires human verification"
- `junit.py` — JUnit XML for CI pass/fail gates
