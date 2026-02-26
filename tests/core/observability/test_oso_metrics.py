from __future__ import annotations

from libp2p.observability.oso.metrics import (
    calculate_contributor_trend,
    calculate_dependency_topology,
    calculate_issue_responsiveness,
    calculate_release_cadence,
    calculate_security_proxy,
)
from libp2p.observability.oso.models import (
    DependencyEntry,
    DependencyGraph,
    ProjectMetadata,
)
from libp2p.observability.oso.providers import CommitInfo, IssueInfo, ReleaseInfo


def _build_graph() -> DependencyGraph:
    return DependencyGraph(
        project=ProjectMetadata(
            name="libp2p",
            version="0.1.0",
            python_version=">=3.10,<4.0",
            repository="https://github.com/libp2p/py-libp2p",
        ),
        dependencies=[
            DependencyEntry(
                name="requests",
                version_spec=">=2.28.0",
                condition=None,
                dependency_type="runtime",
            ),
            DependencyEntry(
                name="requests",
                version_spec=">=2.25.0",
                condition=None,
                dependency_type="runtime",
            ),
        ],
        optional_dependencies={},
        edges=[("libp2p", "requests"), ("libp2p", "requests")],
    )


def test_calculate_dependency_topology_detects_duplicates() -> None:
    metric = calculate_dependency_topology(_build_graph())
    assert metric.direct_dependencies == 2
    assert metric.unique_packages == 1
    assert metric.duplicate_packages == ["requests"]


def test_release_cadence_aggregates_deltas() -> None:
    releases = [
        ReleaseInfo(published_at="2026-02-01T00:00:00Z"),
        ReleaseInfo(published_at="2026-01-22T00:00:00Z"),
        ReleaseInfo(published_at="2026-01-12T00:00:00Z"),
    ]
    metric = calculate_release_cadence(releases)
    assert metric.releases_considered == 3
    assert metric.average_days_between_releases is not None
    assert metric.median_days_between_releases is not None


def test_issue_responsiveness_uses_first_response_and_close_time() -> None:
    issues = [
        IssueInfo(
            created_at="2026-01-01T00:00:00Z",
            first_response_at="2026-01-01T06:00:00Z",
            closed_at="2026-01-02T00:00:00Z",
        ),
        IssueInfo(
            created_at="2026-01-03T00:00:00Z",
            first_response_at="2026-01-03T12:00:00Z",
            closed_at=None,
        ),
    ]
    metric = calculate_issue_responsiveness(issues)
    assert metric.issues_considered == 2
    assert metric.open_issues == 1
    assert metric.closed_issues == 1
    assert metric.median_hours_to_first_response == 9.0


def test_contributor_trend_counts_unique_logins() -> None:
    commits = [
        CommitInfo(committed_at="2026-01-01T00:00:00Z", author_login="alice"),
        CommitInfo(committed_at="2026-01-02T00:00:00Z", author_login="alice"),
        CommitInfo(committed_at="2026-01-09T00:00:00Z", author_login="bob"),
    ]
    metric = calculate_contributor_trend(commits)
    assert metric.commits_considered == 3
    assert metric.unique_contributors == 2
    assert len(metric.weekly_commit_counts) >= 1


def test_security_proxy_uses_vulnerable_and_duplicates() -> None:
    metric = calculate_security_proxy(_build_graph(), vulnerable_packages=["requests"])
    assert metric.duplicate_dependency_specs == ["requests"]
    assert metric.osv_vulnerable_packages == ["requests"]
