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
    avg_days = metrics.release_cadence.average_days_between_releases
    median_days = metrics.release_cadence.median_days_between_releases
    median_first_response = metrics.issue_responsiveness.median_hours_to_first_response
    median_close = metrics.issue_responsiveness.median_hours_to_close
    avg_days_display = f"{avg_days:.2f}" if avg_days is not None else "n/a"
    median_days_display = f"{median_days:.2f}" if median_days is not None else "n/a"
    median_first_response_display = (
        f"{median_first_response:.2f}" if median_first_response is not None else "n/a"
    )
    median_close_display = f"{median_close:.2f}" if median_close is not None else "n/a"
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
            "### rcmgr Metric Family Guide",
            "",
            (
                "- `libp2p_rcmgr_connections`: tracks connection counts/limits "
                "managed by rcmgr."
            ),
            (
                "- `libp2p_rcmgr_streams`: tracks stream counts/limits across "
                "protocol traffic."
            ),
            (
                "- `libp2p_rcmgr_memory`: tracks memory usage and memory-limit "
                "enforcement signals."
            ),
            (
                "- `libp2p_rcmgr_fds`: tracks file-descriptor usage and related "
                "resource pressure."
            ),
            (
                "- `libp2p_rcmgr_blocked_resources`: tracks operations denied by "
                "rcmgr limits (throttling/block events)."
            ),
            (
                "- note: this section reports capability/availability; use live "
                "metrics endpoints for current runtime values."
            ),
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
            "- Runtime Packages (name + version constraint):",
            "",
            *[
                f"  - `{item}`"
                for item in metrics.dependency_topology.runtime_package_versions
            ],
            "",
            "### Release Cadence",
            "",
            f"- releases_considered: `{metrics.release_cadence.releases_considered}`",
            (f"- avg_days_between_releases: `{avg_days_display}`"),
            (f"- median_days_between_releases: `{median_days_display}`"),
            f"- last_release_at: `{metrics.release_cadence.last_release_at or 'n/a'}`",
            ("- interpretation: lower day values indicate more frequent releases."),
            "",
            "### Issue Responsiveness",
            "",
            f"- issues_considered: `{metrics.issue_responsiveness.issues_considered}`",
            f"- median_hours_to_first_response: `{median_first_response_display}`",
            (f"- median_hours_to_close: `{median_close_display}`"),
            f"- open_issues: `{metrics.issue_responsiveness.open_issues}`",
            f"- closed_issues: `{metrics.issue_responsiveness.closed_issues}`",
            (
                "- interpretation: "
                "lower first-response and close times indicate "
                "faster maintenance throughput."
            ),
            "",
            "### Contributor Trend",
            "",
            f"- commits_considered: `{metrics.contributor_trend.commits_considered}`",
            f"- unique_contributors: `{metrics.contributor_trend.unique_contributors}`",
            "- Contributors (GitHub logins):",
            "",
            *[
                f"  - `{login}`"
                for login in metrics.contributor_trend.contributor_logins
            ],
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
                "- note: `version-aware` when installed versions are available; "
                "falls back to package-name lookup otherwise"
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
