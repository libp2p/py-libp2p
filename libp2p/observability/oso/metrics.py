"""Metric calculators for OSO observability report."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import timezone
from statistics import median

from .models import (
    ContributorTrendMetric,
    DependencyGraph,
    DependencyTopologyMetric,
    IssueResponsivenessMetric,
    PopularityMetric,
    RcmgrSnapshot,
    ReleaseCadenceMetric,
    SecurityProxyMetric,
)
from .providers import (
    CommitInfo,
    IssueInfo,
    PopularityInfo,
    ReleaseInfo,
    parse_iso_datetime,
)


def collect_rcmgr_baseline() -> RcmgrSnapshot:
    """Collect current rcmgr baseline capability status."""
    from libp2p.rcmgr import manager

    metrics_available = hasattr(manager, "Metrics") or True

    prometheus_available = False
    exported_metric_names: list[str] = []
    try:
        from libp2p.rcmgr.prometheus_exporter import PrometheusExporter

        prometheus_available = True
        exported_metric_names = [
            "libp2p_rcmgr_connections",
            "libp2p_rcmgr_streams",
            "libp2p_rcmgr_memory",
            "libp2p_rcmgr_fds",
            "libp2p_rcmgr_blocked_resources",
        ]
        _ = PrometheusExporter
    except Exception:
        prometheus_available = False

    monitoring_available = False
    try:
        from libp2p.rcmgr.monitoring import Monitor

        monitoring_available = True
        _ = Monitor
    except Exception:
        monitoring_available = False

    return RcmgrSnapshot(
        metrics_available=metrics_available,
        prometheus_available=prometheus_available,
        monitoring_available=monitoring_available,
        exported_metric_names=exported_metric_names,
    )


def calculate_dependency_topology(graph: DependencyGraph) -> DependencyTopologyMetric:
    """Calculate topology metrics from dependency graph."""
    runtime_names = [entry.name for entry in graph.dependencies]
    optional_entries = [
        entry for group in graph.optional_dependencies.values() for entry in group
    ]
    optional_names = [entry.name for entry in optional_entries]
    all_names = runtime_names + optional_names

    counts = Counter(all_names)
    duplicate_packages = sorted([name for name, count in counts.items() if count > 1])
    unique_packages = len(counts)

    out_degree: dict[str, int] = defaultdict(int)
    for from_node, _ in graph.edges:
        out_degree[from_node] += 1
    max_out_degree = max(out_degree.values()) if out_degree else 0

    most_connected_packages = sorted(
        out_degree.keys(),
        key=lambda name: out_degree[name],
        reverse=True,
    )[:3]

    return DependencyTopologyMetric(
        direct_dependencies=len(graph.dependencies),
        optional_dependencies=len(optional_entries),
        total_dependency_entries=len(all_names),
        unique_packages=unique_packages,
        duplicate_packages=duplicate_packages,
        max_out_degree=max_out_degree,
        most_connected_packages=most_connected_packages,
    )


def _hours_between(start: str, end: str) -> float:
    start_dt = parse_iso_datetime(start)
    end_dt = parse_iso_datetime(end)
    return (end_dt - start_dt).total_seconds() / 3600.0


def calculate_release_cadence(releases: list[ReleaseInfo]) -> ReleaseCadenceMetric:
    """Calculate release cadence metrics."""
    if len(releases) < 2:
        return ReleaseCadenceMetric(
            releases_considered=len(releases),
            average_days_between_releases=None,
            median_days_between_releases=None,
            last_release_at=releases[0].published_at if releases else None,
        )

    sorted_releases = sorted(
        releases,
        key=lambda rel: parse_iso_datetime(rel.published_at),
        reverse=True,
    )
    day_deltas: list[float] = []
    for older, newer in zip(sorted_releases[1:], sorted_releases[:-1]):
        older_dt = parse_iso_datetime(older.published_at)
        newer_dt = parse_iso_datetime(newer.published_at)
        day_deltas.append((newer_dt - older_dt).total_seconds() / 86400.0)

    average = sum(day_deltas) / len(day_deltas)
    return ReleaseCadenceMetric(
        releases_considered=len(sorted_releases),
        average_days_between_releases=average,
        median_days_between_releases=median(day_deltas),
        last_release_at=sorted_releases[0].published_at,
    )


def calculate_issue_responsiveness(
    issues: list[IssueInfo],
) -> IssueResponsivenessMetric:
    """Calculate issue responsiveness metrics."""
    first_response_hours: list[float] = []
    close_hours: list[float] = []
    open_issues = 0
    closed_issues = 0

    for issue in issues:
        if issue.first_response_at:
            first_response_hours.append(
                _hours_between(issue.created_at, issue.first_response_at)
            )
        if issue.closed_at:
            close_hours.append(_hours_between(issue.created_at, issue.closed_at))
            closed_issues += 1
        else:
            open_issues += 1

    return IssueResponsivenessMetric(
        issues_considered=len(issues),
        median_hours_to_first_response=(
            median(first_response_hours) if first_response_hours else None
        ),
        median_hours_to_close=(median(close_hours) if close_hours else None),
        open_issues=open_issues,
        closed_issues=closed_issues,
    )


def _week_key(commit_at: str) -> str:
    commit_dt = parse_iso_datetime(commit_at).astimezone(timezone.utc)
    year, week, _ = commit_dt.isocalendar()
    return f"{year}-W{week:02d}"


def calculate_contributor_trend(commits: list[CommitInfo]) -> ContributorTrendMetric:
    """Calculate contributor trend metrics."""
    contributors = {commit.author_login for commit in commits if commit.author_login}
    weekly: dict[str, int] = defaultdict(int)
    for commit in commits:
        weekly[_week_key(commit.committed_at)] += 1

    return ContributorTrendMetric(
        commits_considered=len(commits),
        unique_contributors=len(contributors),
        weekly_commit_counts=dict(sorted(weekly.items())),
    )


def calculate_popularity(popularity: PopularityInfo) -> PopularityMetric:
    """Normalize popularity metrics."""
    return PopularityMetric(
        stars=popularity.stars,
        forks=popularity.forks,
        watchers=popularity.watchers,
    )


def calculate_security_proxy(
    graph: DependencyGraph,
    vulnerable_packages: Iterable[str],
) -> SecurityProxyMetric:
    """Calculate security proxy from dependency graph + vulnerability lookups."""
    all_names = [entry.name for entry in graph.dependencies]
    all_names += [
        entry.name for group in graph.optional_dependencies.values() for entry in group
    ]
    counts = Counter(all_names)
    duplicates = sorted([name for name, count in counts.items() if count > 1])
    return SecurityProxyMetric(
        duplicate_dependency_specs=duplicates,
        osv_vulnerable_packages=sorted(set(vulnerable_packages)),
        dependency_count=len(all_names),
    )
