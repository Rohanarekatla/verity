# action/

The GitHub Action wrapper that lets other repos run Verity in CI —
`action.yml`, plus whatever composite steps it needs.

Not yet implemented. Depends on the SARIF report generator in
[`verity/report/`](../verity/report/) existing first, since the whole
point of the Action is annotating PRs from that output.
