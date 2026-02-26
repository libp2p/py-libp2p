"""Report rendering and persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path

from .models import HealthReport


def write_json_report(report: HealthReport, output_path: Path) -> None:
    """Write health report as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, indent=2, sort_keys=True)


def render_markdown_report(report: HealthReport) -> str:
    """Render health report as concise markdown."""
    metrics = report.metrics
    exported_names = ", ".join(report.rcmgr_baseline.exported_metric_names)
    duplicate_packages = (
        ", ".join(metrics.dependency_topology.duplicate_packages) or "none"
    )
    duplicate_specs = ", ".join(metrics.security_proxy.duplicate_dependency_specs)
    vulnerable_packages = ", ".join(metrics.security_proxy.osv_vulnerable_packages)
    lines: list[str] = [
        "# py-libp2p OSO Health Report",
        "",
        f"- Generated at: `{report.generated_at}`",
        f"- Project: `{report.project.name}` (`{report.project.version}`)",
        f"- Repository: `{report.project.repository}`",
        "",
        "## Source Status",
        "",
        f"- GitHub: `{report.source_status.github}`",
        f"- OSO: `{report.source_status.oso}`",
        f"- rcmgr: `{report.source_status.rcmgr}`",
    ]
    if report.source_status.notes:
        lines.extend(["", "### Notes", ""])
        lines.extend([f"- {note}" for note in report.source_status.notes])

    lines.extend(
        [
            "",
            "## rcmgr Baseline",
            "",
            f"- metrics_available: `{report.rcmgr_baseline.metrics_available}`",
            f"- prometheus_available: `{report.rcmgr_baseline.prometheus_available}`",
            f"- monitoring_available: `{report.rcmgr_baseline.monitoring_available}`",
            f"- exported_metric_names: `{exported_names}`",
            "",
            "## V1 Metrics",
            "",
            "### Dependency Topology",
            "",
            (
                "- direct_dependencies: "
                f"`{metrics.dependency_topology.direct_dependencies}`"
            ),
            (
                "- optional_dependencies: "
                f"`{metrics.dependency_topology.optional_dependencies}`"
            ),
            f"- unique_packages: `{metrics.dependency_topology.unique_packages}`",
            f"- duplicate_packages: `{duplicate_packages}`",
            "",
            "### Release Cadence",
            "",
            f"- releases_considered: `{metrics.release_cadence.releases_considered}`",
            (
                "- avg_days_between_releases: "
                f"`{metrics.release_cadence.average_days_between_releases}`"
            ),
            (
                "- median_days_between_releases: "
                f"`{metrics.release_cadence.median_days_between_releases}`"
            ),
            "",
            "### Issue Responsiveness",
            "",
            f"- issues_considered: `{metrics.issue_responsiveness.issues_considered}`",
            "- median_hours_to_first_response: "
            f"`{metrics.issue_responsiveness.median_hours_to_first_response}`",
            (
                "- median_hours_to_close: "
                f"`{metrics.issue_responsiveness.median_hours_to_close}`"
            ),
            "",
            "### Contributor Trend",
            "",
            f"- commits_considered: `{metrics.contributor_trend.commits_considered}`",
            f"- unique_contributors: `{metrics.contributor_trend.unique_contributors}`",
            "",
            "### Popularity",
            "",
            f"- stars: `{metrics.popularity.stars}`",
            f"- forks: `{metrics.popularity.forks}`",
            f"- watchers: `{metrics.popularity.watchers}`",
            "",
            "### Security Proxy",
            "",
            (
                "- note: `experimental` (OSV package-name lookups can over-report "
                "without version matching)"
            ),
            f"- duplicate_dependency_specs: `{duplicate_specs or 'none'}`",
            f"- osv_vulnerable_packages: `{vulnerable_packages or 'none'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_markdown_report(report: HealthReport, output_path: Path) -> None:
    """Write report in Markdown format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown_report(report), encoding="utf-8")
