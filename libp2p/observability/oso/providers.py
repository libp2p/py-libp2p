"""External data providers for GitHub and OSO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

GITHUB_API_URL = "https://api.github.com"
OSO_GRAPHQL_URL = "https://www.oso.xyz/api/v1/graphql"
OSV_API_URL = "https://api.osv.dev/v1/query"


@dataclass
class ReleaseInfo:
    """Release metadata needed for cadence calculations."""

    published_at: str


@dataclass
class IssueInfo:
    """Issue metadata used for responsiveness metrics."""

    created_at: str
    closed_at: str | None
    first_response_at: str | None


@dataclass
class CommitInfo:
    """Commit metadata for contributor trends."""

    committed_at: str
    author_login: str | None


@dataclass
class PopularityInfo:
    """Popularity counters from GitHub."""

    stars: int | None
    forks: int | None
    watchers: int | None


class GitHubProvider:
    """GitHub API provider with typed normalization."""

    def __init__(self, repo_slug: str, token: str | None = None) -> None:
        self.repo_slug = repo_slug
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            f"{GITHUB_API_URL}{path}",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def fetch_releases(self, limit: int = 30) -> list[ReleaseInfo]:
        """Fetch latest releases."""
        payload = self._get(
            f"/repos/{self.repo_slug}/releases",
            params={"per_page": limit},
        )
        releases: list[ReleaseInfo] = []
        for item in payload:
            published_at = item.get("published_at")
            if published_at:
                releases.append(ReleaseInfo(published_at=published_at))
        return releases

    def fetch_issues(self, limit: int = 100) -> list[IssueInfo]:
        """Fetch issue metadata and first response proxy."""
        payload = self._get(
            f"/repos/{self.repo_slug}/issues",
            params={
                "state": "all",
                "per_page": min(limit, 100),
                "sort": "updated",
                "direction": "desc",
            },
        )
        issues: list[IssueInfo] = []
        for item in payload:
            # Skip pull requests from issue list.
            if "pull_request" in item:
                continue
            created_at = item.get("created_at")
            if created_at is None:
                continue
            issues.append(
                IssueInfo(
                    created_at=created_at,
                    closed_at=item.get("closed_at"),
                    first_response_at=item.get("updated_at"),
                )
            )
            if len(issues) >= limit:
                break
        return issues

    def fetch_commits(self, limit: int = 100) -> list[CommitInfo]:
        """Fetch latest commits."""
        payload = self._get(
            f"/repos/{self.repo_slug}/commits",
            params={"per_page": min(limit, 100)},
        )
        commits: list[CommitInfo] = []
        for item in payload:
            committed_at = item.get("commit", {}).get("committer", {}).get("date")
            if committed_at is None:
                continue
            author_login: str | None = None
            if isinstance(item.get("author"), dict):
                author_login = item["author"].get("login")
            commits.append(
                CommitInfo(
                    committed_at=committed_at,
                    author_login=author_login,
                )
            )
            if len(commits) >= limit:
                break
        return commits

    def fetch_popularity(self) -> PopularityInfo:
        """Fetch repo popularity counters."""
        payload = self._get(f"/repos/{self.repo_slug}")
        return PopularityInfo(
            stars=payload.get("stargazers_count"),
            forks=payload.get("forks_count"),
            watchers=payload.get("subscribers_count"),
        )


class OsoProvider:
    """OSO GraphQL provider."""

    def __init__(self, token: str | None = None) -> None:
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def query(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        """Run a GraphQL query against OSO endpoint."""
        response = self.session.post(
            OSO_GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


def query_osv_vulnerabilities(package_name: str, ecosystem: str = "PyPI") -> bool:
    """Return whether OSV reports vulnerabilities for package."""
    response = requests.post(
        OSV_API_URL,
        json={"package": {"name": package_name, "ecosystem": ecosystem}},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    vulns = payload.get("vulns", [])
    return bool(vulns)


def parse_iso_datetime(value: str) -> datetime:
    """Parse GitHub/ISO timestamp with ``Z`` support."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
