"""CLI entrypoint for OSO health reporting."""

from __future__ import annotations

from argparse import ArgumentParser
import os
from pathlib import Path

from .report import write_json_report, write_markdown_report
from .service import collect_health_report


def build_parser() -> ArgumentParser:
    """Build CLI parser."""
    parser = ArgumentParser(description="Generate py-libp2p OSO health report")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Path to repository root containing pyproject.toml",
    )
    parser.add_argument(
        "--repo-slug",
        type=str,
        default="libp2p/py-libp2p",
        help="GitHub repository slug (owner/repo)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("reports/health_metrics.json"),
        help="JSON output path",
    )
    parser.add_argument(
        "--md-output",
        type=Path,
        default=Path("reports/health_report.md"),
        help="Markdown output path",
    )
    return parser


def main() -> int:
    """Run CLI and return process status code."""
    parser = build_parser()
    args = parser.parse_args()

    github_token = os.getenv("GITHUB_TOKEN")
    oso_token = os.getenv("OSO_API_KEY")
    report = collect_health_report(
        repo_root=args.repo_root,
        repo_slug=args.repo_slug,
        github_token=github_token,
        oso_token=oso_token,
    )

    write_json_report(report, args.json_output)
    write_markdown_report(report, args.md_output)
    print(f"Wrote JSON report to {args.json_output}")
    print(f"Wrote Markdown report to {args.md_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
