"""Orchestration service for OSO health reports."""

from __future__ import annotations

from pathlib import Path

from .dependency_graph import build_dependency_graph
from .metrics import (
    calculate_contributor_trend,
    calculate_dependency_topology,
    calculate_issue_responsiveness,
    calculate_popularity,
    calculate_release_cadence,
    calculate_security_proxy,
    collect_rcmgr_baseline,
)
from .models import HealthMetrics, HealthReport, SourceStatus, utc_now_iso
from .providers import GitHubProvider, OsoProvider, query_osv_vulnerabilities


def collect_health_report(
    repo_root: Path,
    repo_slug: str = "libp2p/py-libp2p",
    github_token: str | None = None,
    oso_token: str | None = None,
) -> HealthReport:
    """Collect a full health report for py-libp2p."""
    notes: list[str] = []
    notes.append(
        "Security proxy is experimental: OSV lookups currently use package-name "
        "queries and may over-report if fixed versions are installed."
    )
    pyproject_path = repo_root / "pyproject.toml"
    dependency_graph = build_dependency_graph(
        pyproject_path, f"https://github.com/{repo_slug}"
    )
    rcmgr_baseline = collect_rcmgr_baseline()

    github_status = "ok"
    oso_status = "not_configured"
    github = GitHubProvider(repo_slug=repo_slug, token=github_token)

    try:
        releases = github.fetch_releases(limit=30)
        issues = github.fetch_issues(limit=100)
        commits = github.fetch_commits(limit=100)
        popularity = github.fetch_popularity()
    except Exception as error:
        github_status = "error"
        notes.append(f"GitHub provider failed: {error}")
        releases = []
        issues = []
        commits = []
        from .providers import PopularityInfo

        popularity = PopularityInfo(stars=None, forks=None, watchers=None)

    if oso_token:
        oso_status = "ok"
        try:
            oso = OsoProvider(token=oso_token)
            _ = oso.query(
                "query HealthCheck { oso_projectsV1(limit: 1) { projectName } }"
            )
        except Exception as error:
            oso_status = "error"
            notes.append(f"OSO provider failed: {error}")

    vulnerable_packages: list[str] = []
    for dep in dependency_graph.dependencies:
        try:
            if query_osv_vulnerabilities(dep.name):
                vulnerable_packages.append(dep.name)
        except Exception as error:
            notes.append(f"OSV lookup failed for {dep.name}: {error}")
            break

    metrics = HealthMetrics(
        dependency_topology=calculate_dependency_topology(dependency_graph),
        release_cadence=calculate_release_cadence(releases),
        issue_responsiveness=calculate_issue_responsiveness(issues),
        contributor_trend=calculate_contributor_trend(commits),
        popularity=calculate_popularity(popularity),
        security_proxy=calculate_security_proxy(dependency_graph, vulnerable_packages),
    )

    return HealthReport(
        generated_at=utc_now_iso(),
        project=dependency_graph.project,
        source_status=SourceStatus(
            github=github_status,
            oso=oso_status,
            rcmgr="ok",
            notes=notes,
        ),
        rcmgr_baseline=rcmgr_baseline,
        metrics=metrics,
    )
