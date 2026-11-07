# rulepacks/

Community rule packs (`*.verity-rule.yaml`) — project-specific checks on top
of Verity's built-in ones, without forking the engine. Implementation and
rules: [`verity/plugins.py`](../verity/plugins.py).

- **Fixtures are mandatory.** Every pack names a `pass` and a `fail` HTML
  fixture under [`fixtures/`](fixtures/). The pack must report nothing on the
  pass fixture and at least one finding on the fail fixture, or it is not
  loaded. Check with `uv run python -m verity.cli rules verify rulepacks/`.
- **Prefer declarative rules** (`select` + one `assert`): no code runs.
- **Python rules** (`script:` with `check(html) -> [{selector, message}]`) run
  in a restricted subprocess — no network, no writes outside a temp directory,
  empty environment, time and (on POSIX) CPU/memory limits. Best-effort, not a
  container: only enable packs whose code you would run yourself.
- **Community findings never gate a build** — they are reported as
  *needs review*.

Use them in a scan: `uv run python -m verity.cli scan <url> --rules rulepacks/`.

`example-icon-buttons.verity-rule.yaml` is a working example.
