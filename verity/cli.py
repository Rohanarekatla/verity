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
from verity.models.schemas import AuditReport, Provenance

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


async def run_cli_scan(
    url: str,
    output_path: Optional[str] = None,
    timeout: float = 30.0,
    worker_cmd: Optional[list[str]] = None,
) -> int:
    """Runs the scan orchestrator and saves/prints output."""
    try:
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

        # B1.4: non-zero exit when authoritative findings exist, zero on a
        # clean page. Only AUTHORITATIVE findings gate — AI-assisted and
        # needs-review annotate but must never fail a build. This is the
        # default `fail_on: authoritative` policy, hard-coded until the
        # configurable gating policy lands in Week 8 (B8.4).
        gating = [
            f for f in report.findings
            if f.provenance is Provenance.AUTHORITATIVE
            and f.outcome == "fail"
            and not f.waived
        ]
        if gating:
            logger.info(
                f"{len(gating)} authoritative finding(s) — failing with exit code 1."
            )
            return 1

        return 0

    except Exception as exc:
        logger.error(f"Scan failed: {exc}")
        return 1


def main() -> None:
    """CLI Argument Parser entry point."""
    parser = argparse.ArgumentParser(
        prog="verity",
        description="VERITY: WCAG Accessibility Conformance Engine CLI",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 'scan' command parser
    scan_parser = subparsers.add_parser("scan", help="Scan a target URL for WCAG violations")
    scan_parser.add_argument("url", type=str, help="Target URL to audit (e.g., https://example.com)")
    scan_parser.add_argument(
        "-o", "--output", type=str, default=None, help="File path to save JSON report output"
    )
    scan_parser.add_argument(
        "-t", "--timeout", type=float, default=30.0, help="RPC request timeout in seconds (default: 30.0)"
    )
    scan_parser.add_argument(
        "--worker-cmd",
        type=str,
        default=None,
        help="Custom command to run Node worker (e.g. 'node node-worker/dist/index.js')",
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
            )
        )
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()