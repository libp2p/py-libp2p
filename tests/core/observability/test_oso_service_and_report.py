from __future__ import annotations

from pathlib import Path

from libp2p.observability.oso.report import render_markdown_report
from libp2p.observability.oso.service import collect_health_report


def test_collect_health_report_with_mocked_providers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "libp2p"
version = "0.1.0"
requires-python = ">=3.10,<4.0"
dependencies = ["requests>=2.30.0"]
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    from libp2p.observability.oso import service
    from libp2p.observability.oso.providers import (
        CommitInfo,
        IssueInfo,
        PopularityInfo,
        ReleaseInfo,
    )

    monkeypatch.setattr(
        service.GitHubProvider,
        "fetch_releases",
        lambda self, limit=30: [ReleaseInfo(published_at="2026-01-01T00:00:00Z")],
    )
    monkeypatch.setattr(
        service.GitHubProvider,
        "fetch_issues",
        lambda self, limit=100: [
            IssueInfo(
                created_at="2026-01-01T00:00:00Z",
                first_response_at="2026-01-01T01:00:00Z",
                closed_at=None,
            )
        ],
    )
    monkeypatch.setattr(
        service.GitHubProvider,
        "fetch_commits",
        lambda self, limit=100: [
            CommitInfo(
                committed_at="2026-01-01T00:00:00Z",
                author_login="alice",
            )
        ],
    )
    monkeypatch.setattr(
        service.GitHubProvider,
        "fetch_popularity",
        lambda self: PopularityInfo(stars=1, forks=2, watchers=3),
    )
    monkeypatch.setattr(
        service,
        "query_osv_vulnerabilities",
        lambda package_name: False,
    )

    report = collect_health_report(
        repo_root=tmp_path,
        repo_slug="libp2p/py-libp2p",
        github_token=None,
        oso_token=None,
    )

    assert report.project.name == "libp2p"
    assert report.metrics.popularity.stars == 1
    assert report.metrics.dependency_topology.direct_dependencies == 1

    markdown = render_markdown_report(report)
    assert "# py-libp2p OSO Health Report" in markdown
    assert "Source Status" in markdown
