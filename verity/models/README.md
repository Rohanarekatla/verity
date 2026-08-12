# verity/models/

`schemas.py` — Pydantic definitions for every data shape in the
system: the single source of truth for types on both sides of the
language boundary. JSON Schema generated from these models is what
dictates the TypeScript types on the Node side (see
[ADR 0001](../../docs/adr/0001-polyglot-json-rpc-over-stdio.md)).

Enums: `Level`, `Severity`, `Provenance`, `Modality`.
Models: `BoundingBox`, `SuccessCriterion`, `Evidence`, `Confidence`,
`Finding`, `PageState`, `RenderArtifact`, `AuditReport`.

`Provenance` is required on `Finding` with no default — a finding that
can't say where it came from is a bug, not something to paper over
with a default value.
