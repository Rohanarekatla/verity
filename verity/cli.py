"""
verity/cli.py
Command-Line Interface (CLI) entry point for the VERITY accessibility engine.
"""

import argparse
import asyncio
import json
import sys
import logging
from pathlib import Path
from typing import Optional

from verity.orchestrator.main import scan_url
from verity.models.schemas import AuditReport

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("verity-cli")


def print_report_summary(report: AuditReport) -> None:
    """Prints a clean, human-readable terminal summary of the audit report."""
    print("\n" + "=" * 60)
    print(f" VERITY ACCESSIBILITY AUDIT REPORT")
    print("=" * 60)
    print(f" Target URL     : {report.target}")
    print(f" WCAG Standard  : {report.standard}")
    print(f" Verity Version : {report.verity_version}")
    print(f" Total Findings : {len(report.findings)}")
    print("-" * 60)

    if not report.findings:
        print(" SUCCESS: No deterministic accessibility violations detected!")
    else:
        print(" FINDINGS SUMMARY:")
        for idx, finding in enumerate(report.findings, start=1):
            severity_str = finding.severity.value.upper()
            sc_id = finding.sc.id
            selector = finding.evidence.dom_selector or "N/A"
            print(f"  {idx}. [{severity_str}] SC {sc_id} - {finding.message}")
            print(f"     Selector: {selector}")

    print("=" * 60 + "\n")


def report_expired_waivers(waivers_path: Optional[str] = None) -> list[str]:
    """
    B7.3 — print every expired waiver by name and return them.

    Returns the descriptions rather than just a count, so a caller can put
    them somewhere else (a PR annotation, Week 8's SARIF) without re-reading
    the file.

    A waiver file that is itself broken is surfaced here, then **re-raised**.
    If we cannot tell which findings are suppressed, we have no trustworthy
    verdict at all — that is a scan that could not complete (exit 2), not a
    page with gating failures (exit 1). Returning it as an ordinary "expired
    waiver" used to map it to exit 1, telling CI the *site* was inaccessible
    when the real problem was our own config.

    That branch was unreachable from `run_cli_scan` (the scan loads the same
    file first and raises), but only by accident of call order. Re-raising
    makes the doctrine hold wherever this is called — including the obvious
    refactor of checking config *before* a 2-minute render.
    """
    from verity.agents.validator.waivers import (
        WaiverFileError,
        expired_waivers,
        expiring_soon,
        load_waivers,
    )

    try:
        waivers = load_waivers(waivers_path)
    except WaiverFileError as exc:
        print("\n  WAIVER FILE INVALID")
        for line in str(exc).splitlines():
            print(f"  {line}")
        print()
        raise

    expired = expired_waivers(waivers)
    if expired:
        print("\n  EXPIRED WAIVERS — these no longer suppress anything:")
        for item in expired:
            print(f"    - {item.describe()}")
        print(
            "\n  Renew with a new `expires` date, or fix the finding and "
            "delete the waiver.\n"
        )

    # A hard expiry with no warning turns a deliberate policy into a surprise
    # red build on an unrelated PR, so warn before it bites.
    for signature, waiver, days in expiring_soon(waivers):
        logger.warning(
            "Waiver %s… expires in %d day(s) on %s (approved by %s)",
            signature[:12], days, waiver.expires, waiver.approved_by,
        )

    return [item.describe() for item in expired]


# Exit codes. 1 and 2 must stay distinct: in CI, 1 means "this page has
# gating accessibility failures", and a scan that crashed (site unreachable,
# render timeout, worker missing) is not evidence of any. Reporting a crash as
# exit 1 told a pipeline the site was inaccessible when we had not looked.
EXIT_OK = 0
EXIT_GATING_FINDINGS = 1
EXIT_SCAN_ERROR = 2

# A real page (load, best-effort network idle, DOM settle, full-page capture)
# can legitimately take over a minute; 30s timed out on github.com and friends.
DEFAULT_TIMEOUT_S = 120.0


def normalize_target(target: str) -> str:
    """
    Accept a local file path as well as a URL. `verity scan ./dist/index.html`
    is the first thing a new user types, and it used to fail with Playwright's
    "Cannot navigate to invalid URL".
    """
    if not target or "://" in target or target.startswith(("about:", "data:")):
        return target
    path = Path(target).expanduser()
    # Files only: a directory would render Chromium's folder listing and be
    # audited as though it were a page.
    if path.is_file():
        return path.resolve().as_uri()
    return target


async def run_cli_scan(
    url: str,
    output_path: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    worker_cmd: Optional[list[str]] = None,
    sarif_path: Optional[str] = None,
    junit_path: Optional[str] = None,
    config_path: Optional[str] = None,
    write_baseline_path: Optional[str] = None,
    baseline_path: Optional[str] = None,
) -> int:
    """Runs the scan orchestrator and saves/prints output."""
    from verity.report.policy import load_policy
    from verity.report.regression import gate_against_baseline, open_baseline

    try:
        # B8.4 — the gating policy is loaded before the scan, so a bad `ci:`
        # block fails immediately rather than after a 30-second render.
        policy = load_policy(config_path)
        logger.info("CI policy: %s", policy.describe())

        # B7.4 — same reasoning: a missing or hand-edited baseline is a config
        # error, surfaced before the render (exit 2), not after it.
        baseline = open_baseline(baseline_path)

        url = normalize_target(url)
        logger.info(f"Starting scan for URL: {url}")
        report: AuditReport = await scan_url(
            url=url, node_worker_command=worker_cmd, timeout=timeout
        )

        # Print human-readable summary
        print_report_summary(report)

        # Save to JSON file if requested
        if output_path:
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))
            logger.info(f"Audit report saved successfully to: {out_file.resolve()}")

        # B8.1/B8.2 — SARIF for GitHub code scanning.
        if sarif_path:
            from verity.report.sarif import repo_relative_path, write_sarif

            written = write_sarif(report, sarif_path, policy=policy)
            logger.info(f"SARIF written to: {written.resolve()}")
            if repo_relative_path(report.target) is None:
                # Say it out loud rather than letting someone wonder why no
                # annotation appeared. See docs/sarif-reference.md §5.
                logger.warning(
                    "Target %r is not a file inside the repository, so GitHub "
                    "cannot place inline PR annotations; findings will appear "
                    "in the Security tab only.",
                    report.target,
                )

        # B8.3 — JUnit for every CI that is not GitHub Actions.
        if junit_path:
            from verity.report.junit import write_junit

            written = write_junit(report, junit_path, policy=policy)
            logger.info(f"JUnit XML written to: {written.resolve()}")

        # A7.2 / A8.3 — record the current findings as a baseline. This is how
        # the baseline-commit workflow regenerates the file it proposes in a
        # PR. Writing a baseline is not gating: it reflects whatever the scan
        # found, so it runs regardless of the exit code below.
        if write_baseline_path:
            from verity.report.baseline import build_baseline, write_baseline

            recorded = build_baseline(report)
            write_baseline(recorded, Path(write_baseline_path))
            logger.info(
                "Baseline written to %s (%d finding(s), id %s)",
                write_baseline_path,
                len(recorded.entries),
                recorded.baseline_id[:12],
            )

        # B7.3 — an expired waiver fails CI, by name.
        #
        # Checked before the findings gate and reported separately, because
        # the two mean different things. A failing finding says "your page
        # has a defect"; an expired waiver says "a decision you made has run
        # out and nobody renewed it". Collapsing them into one exit code
        # would leave a team fixing the wrong thing.
        #
        # Note the finding this waiver used to cover has *also* reappeared
        # and may be in `gating` below — that is deliberate, not double
        # reporting. See process_findings.
        expiry_failures = report_expired_waivers()

        # B8.4 — gating is now the policy's decision, not a hardcoded rule.
        # The default is still `fail_on: authoritative`: only deterministic
        # verdicts gate, and AI-assisted or needs-review findings annotate
        # without ever breaking a build. A team can widen or disable it via
        # `ci:` in their config, which is how report-only adoption works on
        # day one.
        #
        # B7.4 — with a baseline, only findings *absent from it* can gate:
        # one new defect fails the build on exactly that one, not on the
        # fifty already accepted. An incompatible baseline raises (exit 2).
        if baseline is not None:
            from verity.report.baseline import format_diff

            result = gate_against_baseline(baseline, report, policy)
            print(format_diff(result.diff) + "\n")
            logger.info("Regression gate keyed to %s", result.key.describe())
            gating = result.gating
        else:
            gating = policy.gating_findings(report.findings)
        if gating:
            logger.info(
                "%d gating finding(s) under %s — failing with exit code %d.",
                len(gating),
                policy.describe(),
                EXIT_GATING_FINDINGS,
            )
            return EXIT_GATING_FINDINGS

        # An expired waiver is a valid file whose decision has lapsed: the
        # team must act, so it gates. A *broken* waiver file never reaches
        # here — it raises and exits EXIT_SCAN_ERROR above.
        if expiry_failures:
            return EXIT_GATING_FINDINGS

        return EXIT_OK

    except Exception as exc:
        logger.error(
            f"Scan failed: {exc or exc.__class__.__name__}. "
            f"No accessibility verdict was reached (exit {EXIT_SCAN_ERROR})."
        )
        return EXIT_SCAN_ERROR


def run_agent_check_cli(
    url: str,
    task: str,
    *,
    success: Optional[str] = None,
    model_spec: str = "ollama:llama3.1",
    json_path: Optional[str] = None,
    sarif_path: Optional[str] = None,
    html_path: Optional[str] = None,
    config_path: Optional[str] = None,
    headless: bool = True,
) -> int:
    """
    A14.1′/A14.2′ — run `verity agent-check`.

    An LLM agent attempts `task` on `url` through the accessibility tree +
    keyboard. A failure is localised and reported, but — the Week-14 safety rule
    — only as `needs-review` unless a deterministic confirmer (B14.1′) upgrades
    it, so an unconfirmed agent failure never gates CI. Success, when `--success`
    is given, is decided by the deterministic evaluators, never a model.
    """
    from eval.agentbench.agents.tree_agent import TreeAgent
    from eval.agentbench.loop_guard import LoopGuard
    from eval.agentbench.providers import make_provider
    from eval.agentbench.web_env import WebEnv
    from verity.agent_check.check import agent_check
    from verity.agent_check.report import write_reports
    from verity.report.policy import load_policy

    try:
        policy = load_policy(config_path)
        provider = make_provider(model_spec, allow_unpriced=True)
        agent = TreeAgent(provider, loop_guard=LoopGuard())

        success_fn = None
        if success:
            import yaml

            from eval.agentbench.evaluators import evaluate, observation_from_page

            spec = yaml.safe_load(success)

            def success_fn(env, _spec=spec):  # noqa: E306 — closure over the parsed spec
                obs = observation_from_page(env.page, _spec)
                return evaluate(_spec, obs, task_id=url).outcome

        target = normalize_target(url)
        logger.info("Agent-check: %r on %s via %s", task, target, model_spec)
        with WebEnv(target, goal=task, headless=headless) as env:
            result = agent_check(target, task, agent=agent, env=env, success_fn=success_fn)

        # Gating respects the loaded policy's `fail_on` (agent-check findings are
        # needs-review, so they do not gate); annotation is widened to
        # needs-review so the agent failure actually appears in SARIF.
        from verity.report.policy import CiPolicy

        report_policy = CiPolicy(fail_on=policy.fail_on, annotate_on="everything")
        written = write_reports(result, json_path=json_path, sarif_path=sarif_path,
                                html_path=html_path, policy=report_policy)

        print("\n" + "=" * 60)
        print(" VERITY AGENT-CHECK")
        print("=" * 60)
        print(f" Target : {target}")
        print(f" Task   : {task}")
        print(f" Verdict: {result.verdict.upper()}  (success decided by: {result.success_source})")
        if result.findings:
            f = result.findings[0]
            print("-" * 60)
            print(f" {f.provenance.value.upper()} · SC {f.sc.id} {f.sc.name}")
            print(f"   {f.message}")
            if f.evidence.dom_selector:
                print(f"   element: {f.evidence.dom_selector}")
        for kind, path in written.items():
            print(f" {kind}: {path.resolve()}")
        print("=" * 60 + "\n")

        gating = policy.gating_findings(result.findings)
        if gating:
            logger.info("%d gating finding(s) under %s — exit %d.",
                        len(gating), policy.describe(), EXIT_GATING_FINDINGS)
            return EXIT_GATING_FINDINGS
        return EXIT_OK

    except Exception as exc:
        logger.error(
            "Agent-check failed: %s. No verdict was reached (exit %d).",
            exc or exc.__class__.__name__, EXIT_SCAN_ERROR,
        )
        return EXIT_SCAN_ERROR


def _read_html(target: str) -> str:
    """Read a page's HTML from a local file or a static HTTP(S) GET."""
    from urllib.parse import unquote, urlparse

    if target.startswith("file://"):
        return Path(unquote(urlparse(target).path)).read_text(encoding="utf-8", errors="replace")
    if "://" in target:
        import urllib.request

        req = urllib.request.Request(target, headers={"User-Agent": "verity-webmcp"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    return Path(target).read_text(encoding="utf-8", errors="replace")


def run_webmcp_cli(target: str, *, generate: bool = False, json_path: Optional[str] = None,
                   strict: bool = False) -> int:
    """
    A16.1′/A16.2′ — check a page's WebMCP readiness and, with --generate, emit a
    verified tool declaration for each uncovered form.
    """
    import json as _json

    from verity.webmcp import (
        check_readiness,
        extract_page_from_html,
        generate_tool_for_form,
        verify_tool_against_form,
    )

    try:
        url = normalize_target(target)
        page = extract_page_from_html(_read_html(url), url)
        report = check_readiness(page)

        print("\n" + "=" * 60)
        print(" VERITY WEBMCP READINESS")
        print("=" * 60)
        print(f" Target : {url}")
        print(f" Tools  : {report.tool_count}   Forms: {report.form_count}   Score: {report.score}/100")
        for issue in report.issues:
            print(f"  [{issue.level.upper()}] {issue.code}: {issue.message}")

        generated = []
        if generate and report.uncovered:
            print("-" * 60)
            print(" GENERATED TOOL DECLARATIONS (for uncovered forms):")
            by_selector = {f.selector: f for f in page.forms}
            for selector in report.uncovered:
                form = by_selector[selector]
                tool = generate_tool_for_form(form)
                verification = verify_tool_against_form(tool, form)
                mark = "verified: agent can submit the form" if verification.ok else \
                       "NOT verified: " + "; ".join(verification.reasons)
                print(f"\n  # {selector}  ({mark})")
                print("  " + _json.dumps({"name": tool.name, "description": tool.description,
                                          "inputSchema": tool.input_schema,
                                          "form": tool.form_selector}, indent=2).replace("\n", "\n  "))
                generated.append({"form": selector, "tool": {
                    "name": tool.name, "description": tool.description,
                    "inputSchema": tool.input_schema, "form": tool.form_selector},
                    "verified": verification.ok, "reasons": verification.reasons})
        print("=" * 60 + "\n")

        if json_path:
            out = {"url": url, "score": report.score, "tool_count": report.tool_count,
                   "form_count": report.form_count, "covered": report.covered,
                   "uncovered": report.uncovered, "invalid_schemas": report.invalid_schemas,
                   "issues": [vars(i) for i in report.issues], "generated": generated}
            Path(json_path).write_text(_json.dumps(out, indent=2), encoding="utf-8")
            logger.info("WebMCP report written to %s", json_path)

        errors = [i for i in report.issues if i.level == "error"]
        if strict and errors:
            return EXIT_GATING_FINDINGS
        return EXIT_OK

    except Exception as exc:
        logger.error("WebMCP check failed: %s (exit %d).", exc or exc.__class__.__name__, EXIT_SCAN_ERROR)
        return EXIT_SCAN_ERROR


def main() -> None:
    """CLI Argument Parser entry point."""
    parser = argparse.ArgumentParser(
        prog="verity",
        description="VERITY: WCAG Accessibility Conformance Engine CLI",
        epilog="Exit codes: 0 no gating findings, 1 gating findings, 2 the scan could not complete.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 'scan' command parser
    scan_parser = subparsers.add_parser("scan", help="Scan a target URL for WCAG violations")
    scan_parser.add_argument(
        "url", type=str,
        help="Target URL or local HTML file (e.g., https://example.com or ./dist/index.html)",
    )
    scan_parser.add_argument(
        "-o", "--output", type=str, default=None, help="File path to save JSON report output"
    )
    scan_parser.add_argument(
        "-t", "--timeout", type=float, default=DEFAULT_TIMEOUT_S,
        help=f"RPC request timeout in seconds (default: {DEFAULT_TIMEOUT_S:g})"
    )
    scan_parser.add_argument(
        "--worker-cmd",
        type=str,
        default=None,
        help="Custom command to run Node worker (e.g. 'node node-worker/dist/index.js')",
    )
    # B8.1/B8.2 — SARIF for GitHub code scanning. Inline PR annotations need
    # the target to be a file inside the repo; see docs/sarif-reference.md §5.
    scan_parser.add_argument(
        "--sarif",
        type=str,
        default=None,
        metavar="PATH",
        help="Write SARIF 2.1.0 output for GitHub code scanning",
    )
    # B8.3 — JUnit for every CI that is not GitHub Actions.
    scan_parser.add_argument(
        "--junit",
        type=str,
        default=None,
        metavar="PATH",
        help="Write JUnit XML output (Jenkins, GitLab, CircleCI, Azure)",
    )
    # B8.4 — gating policy. Default stays `fail_on: authoritative`.
    scan_parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="Config file carrying a `ci: { fail_on, annotate_on }` block",
    )
    # A7.2/A8.3 — record this scan's findings as a baseline file. The
    # baseline-commit workflow uses this, then opens a PR with the result.
    scan_parser.add_argument(
        "--write-baseline",
        type=str,
        default=None,
        metavar="PATH",
        help="Write a content-addressed baseline of this scan's findings",
    )
    # B7.4 — gate only on findings that are new relative to a baseline.
    scan_parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        metavar="PATH",
        help="Fail only on findings absent from this baseline (see --write-baseline)",
    )

    # 'agent-check' command (A14.1′/A14.2′) — does an AI agent complete a task?
    ac = subparsers.add_parser(
        "agent-check",
        help="Have an AI agent attempt a task on a URL through the a11y tree; localise failures",
    )
    ac.add_argument("url", type=str, help="Target URL or local HTML file")
    ac.add_argument("--task", type=str, required=True,
                    help='What the agent should do, e.g. "Add the first product to the cart"')
    ac.add_argument("--success", type=str, default=None,
                    help="A deterministic success spec (YAML/JSON) checked after the run; "
                         "without it, success is the agent's own verdict")
    ac.add_argument("--model", type=str, default="ollama:llama3.1", metavar="SPEC",
                    help="Provider spec, e.g. anthropic:claude-sonnet-5-5 or ollama:llama3.1 (default)")
    ac.add_argument("--json", type=str, default=None, metavar="PATH", help="Write the JSON report")
    ac.add_argument("--sarif", type=str, default=None, metavar="PATH",
                    help="Write SARIF for GitHub code scanning / the Verity Action")
    ac.add_argument("--html", type=str, default=None, metavar="PATH",
                    help="Write an HTML trace replaying every step with the tree the agent saw")
    ac.add_argument("-c", "--config", type=str, default=None, metavar="PATH",
                    help="Config file with a `ci: { fail_on, annotate_on }` block")
    ac.add_argument("--headed", action="store_true", help="Show the browser (debugging)")

    # 'mcp' command (A15.1′) — expose Verity's checks as MCP tools over stdio.
    subparsers.add_parser(
        "mcp",
        help="Run the Verity MCP server (stdio) so a coding agent can scan/confirm fixes",
    )

    # 'webmcp' command (A16.1′/A16.2′) — WebMCP readiness + declaration generator.
    wm = subparsers.add_parser(
        "webmcp",
        help="Check a page's WebMCP readiness and generate tool declarations for its forms",
    )
    wm.add_argument("target", type=str, help="Target URL or local HTML file")
    wm.add_argument("--generate", action="store_true",
                    help="Generate a verified WebMCP tool declaration for each uncovered form")
    wm.add_argument("--json", type=str, default=None, metavar="PATH", help="Write the JSON report")
    wm.add_argument("--strict", action="store_true", help="Exit non-zero if any error-level issue")

    args = parser.parse_args()

    if args.command == "webmcp":
        sys.exit(run_webmcp_cli(args.target, generate=args.generate,
                                json_path=args.json, strict=args.strict))
    elif args.command == "mcp":
        from verity.mcp.server import main as mcp_main

        sys.exit(mcp_main())
    elif args.command == "agent-check":
        sys.exit(run_agent_check_cli(
            url=args.url, task=args.task, success=args.success, model_spec=args.model,
            json_path=args.json, sarif_path=args.sarif, html_path=args.html,
            config_path=args.config, headless=not args.headed,
        ))
    elif args.command == "scan":
        worker_cmd_list = args.worker_cmd.split() if args.worker_cmd else None
        exit_code = asyncio.run(
            run_cli_scan(
                url=args.url,
                output_path=args.output,
                timeout=args.timeout,
                worker_cmd=worker_cmd_list,
                sarif_path=args.sarif,
                junit_path=args.junit,
                config_path=args.config,
                write_baseline_path=args.write_baseline,
                baseline_path=args.baseline,
            )
        )
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()