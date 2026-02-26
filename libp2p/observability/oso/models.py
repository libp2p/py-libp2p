"""Typed models for OSO observability reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, cast


def utc_now_iso() -> str:
    """Return an ISO8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProjectMetadata:
    """Project identity metadata."""

    name: str
    version: str
    python_version: str
    repository: str


@dataclass
class DependencyEntry:
    """A single dependency declaration entry."""

    name: str
    version_spec: str | None
    condition: str | None
    dependency_type: str


@dataclass
class DependencyGraph:
    """Dependency graph model used for health analysis."""

    project: ProjectMetadata
    dependencies: list[DependencyEntry]
    optional_dependencies: dict[str, list[DependencyEntry]]
    edges: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class RcmgrSnapshot:
    """Snapshot view of local rcmgr runtime-related metrics."""

    metrics_available: bool
    prometheus_available: bool
    monitoring_available: bool
    exported_metric_names: list[str] = field(default_factory=list)


@dataclass
class DependencyTopologyMetric:
    """Dependency graph topology metrics."""

    direct_dependencies: int
    optional_dependencies: int
    total_dependency_entries: int
    unique_packages: int
    duplicate_packages: list[str]
    max_out_degree: int
    most_connected_packages: list[str]


@dataclass
class ReleaseCadenceMetric:
    """Release cadence metric model."""

    releases_considered: int
    average_days_between_releases: float | None
    median_days_between_releases: float | None
    last_release_at: str | None


@dataclass
class IssueResponsivenessMetric:
    """Issue responsiveness metric model."""

    issues_considered: int
    median_hours_to_first_response: float | None
    median_hours_to_close: float | None
    open_issues: int
    closed_issues: int


@dataclass
class ContributorTrendMetric:
    """Contributor activity trend metric model."""

    commits_considered: int
    unique_contributors: int
    weekly_commit_counts: dict[str, int]


@dataclass
class PopularityMetric:
    """Popularity metric model."""

    stars: int | None
    forks: int | None
    watchers: int | None


@dataclass
class SecurityProxyMetric:
    """Security proxy metric model."""

    duplicate_dependency_specs: list[str]
    osv_vulnerable_packages: list[str]
    dependency_count: int


@dataclass
class HealthMetrics:
    """Aggregated V1 health metrics."""

    dependency_topology: DependencyTopologyMetric
    release_cadence: ReleaseCadenceMetric
    issue_responsiveness: IssueResponsivenessMetric
    contributor_trend: ContributorTrendMetric
    popularity: PopularityMetric
    security_proxy: SecurityProxyMetric


@dataclass
class SourceStatus:
    """Data-source status for partial-failure reporting."""

    github: str
    oso: str
    rcmgr: str
    notes: list[str] = field(default_factory=list)


@dataclass
class HealthReport:
    """Top-level report model persisted to JSON/Markdown."""

    generated_at: str
    project: ProjectMetadata
    source_status: SourceStatus
    rcmgr_baseline: RcmgrSnapshot
    metrics: HealthMetrics

    def to_dict(self) -> dict[str, Any]:
        """Serialize report as a plain dict."""
        return asdict(cast(Any, self))
