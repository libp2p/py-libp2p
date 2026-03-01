#!/usr/bin/env python3
"""Validate OSO health report accuracy with lightweight sanity checks."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
import json
from pathlib import Path
import sys

import requests

if sys.version_info >= (3, 11):
    import tomllib as _toml_module
else:
    import tomli as _toml_module  # type: ignore[import]

GITHUB_API_URL = "https://api.github.com"


def _load_json(path: Path) -> dict[str, object]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _extract_dependency_expectation(pyproject_path: Path) -> tuple[int, int, int]:
    with open(pyproject_path, "rb") as handle:
        pyproject_data = _toml_module.load(handle)
    project_data = pyproject_data.get("project", {})
    runtime = project_data.get("dependencies", [])
    optional_groups = project_data.get("optional-dependencies", {})
    optional_total = sum(len(group) for group in optional_groups.values())
    return len(runtime), optional_total, len(runtime) + optional_total


def _github_get(
    session: requests.Session, path: str, params: dict[str, object] | None = None
) -> object:
    response = session.get(
        f"{GITHUB_API_URL}{path}",
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Validate OSO health report accuracy")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/health_metrics.json"),
        help="Path to generated health report JSON",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml used by the report",
    )
    parser.add_argument(
        "--repo-slug",
        type=str,
        default="libp2p/py-libp2p",
        help="GitHub repository slug (owner/repo)",
    )
    parser.add_argument(
        "--github-token",
        type=str,
        default=None,
        help="Optional GitHub token for source-of-truth checks",
    )
    parser.add_argument(
        "--require-github-ok",
        action="store_true",
        help="Fail if report source_status.github is not ok",
    )
    parser.add_argument(
        "--require-oso-ok",
        action="store_true",
        help="Fail if report source_status.oso is not ok",
    )
    return parser


def _report_error(errors: list[str], message: str) -> None:
    errors.append(message)
    print(f"[ERROR] {message}")


def _report_info(message: str) -> None:
    print(f"[INFO] {message}")


def validate(args: Namespace) -> int:
    report = _load_json(args.report)
    errors: list[str] = []

    source_status = report.get("source_status")
    metrics = report.get("metrics")
    if not isinstance(source_status, dict):
        _report_error(errors, "Missing or invalid source_status object")
        return 1
    if not isinstance(metrics, dict):
        _report_error(errors, "Missing or invalid metrics object")
        return 1

    github_status = source_status.get("github")
    oso_status = source_status.get("oso")
    notes = source_status.get("notes", [])

    if args.require_github_ok and github_status != "ok":
        _report_error(errors, f"source_status.github expected ok, got {github_status}")
    if args.require_oso_ok and oso_status != "ok":
        _report_error(errors, f"source_status.oso expected ok, got {oso_status}")

    if github_status == "error" and (not isinstance(notes, list) or not notes):
        _report_error(errors, "github source error reported without explanatory notes")

    dep_topology = metrics.get("dependency_topology")
    security_proxy = metrics.get("security_proxy")
    if not isinstance(dep_topology, dict):
        _report_error(errors, "Missing dependency_topology metric section")
    if not isinstance(security_proxy, dict):
        _report_error(errors, "Missing security_proxy metric section")

    runtime_expected, optional_expected, total_expected = (
        _extract_dependency_expectation(args.pyproject)
    )
    if isinstance(dep_topology, dict):
        runtime_actual = dep_topology.get("direct_dependencies")
        optional_actual = dep_topology.get("optional_dependencies")
        total_actual = dep_topology.get("total_dependency_entries")
        if runtime_actual != runtime_expected:
            _report_error(
                errors,
                (
                    "Runtime dependency count mismatch: "
                    f"expected {runtime_expected}, got {runtime_actual}"
                ),
            )
        if optional_actual != optional_expected:
            _report_error(
                errors,
                (
                    "Optional dependency count mismatch: "
                    f"expected {optional_expected}, got {optional_actual}"
                ),
            )
        if total_actual != total_expected:
            _report_error(
                errors,
                (
                    "Total dependency entry mismatch: "
                    f"expected {total_expected}, got {total_actual}"
                ),
            )

    if args.github_token and github_status == "ok":
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Authorization": f"Bearer {args.github_token}",
            }
        )
        try:
            repo_meta = _github_get(session, f"/repos/{args.repo_slug}")
        except Exception as error:
            _report_error(errors, f"GitHub API check failed: {error}")
            repo_meta = None

        popularity = metrics.get("popularity")
        if isinstance(repo_meta, dict) and isinstance(popularity, dict):
            expected_stars = repo_meta.get("stargazers_count")
            expected_forks = repo_meta.get("forks_count")
            expected_watchers = repo_meta.get("subscribers_count")
            if popularity.get("stars") != expected_stars:
                _report_error(
                    errors,
                    (
                        "Popularity stars mismatch: "
                        f"expected {expected_stars}, got {popularity.get('stars')}"
                    ),
                )
            if popularity.get("forks") != expected_forks:
                _report_error(
                    errors,
                    (
                        "Popularity forks mismatch: "
                        f"expected {expected_forks}, got {popularity.get('forks')}"
                    ),
                )
            if popularity.get("watchers") != expected_watchers:
                actual_watchers = popularity.get("watchers")
                _report_error(
                    errors,
                    (
                        "Popularity watchers mismatch: "
                        f"expected {expected_watchers}, got {actual_watchers}"
                    ),
                )

    _report_info(f"Checked report: {args.report}")
    _report_info(
        f"source_status.github={github_status}, source_status.oso={oso_status}"
    )
    _report_info(
        "Expected dependency counts "(
            f"(runtime={runtime_expected}, optional={optional_expected}, "
            f"total={total_expected})"
        )
    )

    if errors:
        print(f"[RESULT] FAILED ({len(errors)} issues)")
        return 1

    print("[RESULT] PASSED")
    return 0


def main() -> int:
    parser = build_parser()
    return validate(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
