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

    A waiver file that is itself broken is also surfaced here rather than
    swallowed: if we cannot tell which findings are suppressed, continuing as
    though none were would be a guess about someone's accessibility policy.
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
        return [f"waiver file invalid: {exc}"]

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
) -> int:
    """Runs the scan orchestrator and saves/prints output."""
    from verity.report.policy import load_policy

    try:
        # B8.4 — the gating policy is loaded before the scan, so a bad `ci:`
        # block fails immediately rather than after a 30-second render.
        policy = load_policy(config_path)
        logger.info("CI policy: %s", policy.describe())

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

            baseline = build_baseline(report)
            write_baseline(baseline, Path(write_baseline_path))
            logger.info(
                "Baseline written to %s (%d finding(s), id %s)",
                write_baseline_path,
                len(baseline.entries),
                baseline.baseline_id[:12],
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
        gating = policy.gating_findings(report.findings)
        if gating:
            logger.info(
                "%d gating finding(s) under %s — failing with exit code 1.",
                len(gating),
                policy.describe(),
            )
            return 1

        if expiry_failures:
            return 1

        return 0

    except Exception as exc:
        logger.error(
            f"Scan failed: {exc or exc.__class__.__name__}. "
            f"No accessibility verdict was reached (exit {EXIT_SCAN_ERROR})."
        )
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

    args = parser.parse_args()

    if args.command == "scan":
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
            )
        )
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()