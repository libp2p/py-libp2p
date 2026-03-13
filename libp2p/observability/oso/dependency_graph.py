"""Dependency graph extraction and normalization utilities."""

from __future__ import annotations

from pathlib import Path
import re
import sys

from .models import DependencyEntry, DependencyGraph, ProjectMetadata

if sys.version_info >= (3, 11):
    import tomllib as _toml_module
else:
    import tomli as _toml_module  # type: ignore[import]


_NAME_PATTERN = re.compile(r"^([a-zA-Z0-9_.-]+)")


def _split_dependency(dep: str) -> tuple[str, str | None, str | None]:
    """Split dependency string into name/version/condition."""
    condition: str | None = None
    package_part = dep.strip()
    if ";" in package_part:
        package_part, condition = (part.strip() for part in package_part.split(";", 1))

    # Handle `name (spec)` style.
    if "(" in package_part and ")" in package_part:
        match = re.match(r"^([a-zA-Z0-9_.-]+)\s*\((.+)\)$", package_part)
        if match:
            return match.group(1), match.group(2).strip(), condition

    match = _NAME_PATTERN.match(package_part)
    if match is None:
        return package_part, None, condition

    name = match.group(1)
    remainder = package_part[len(name) :].strip()
    version_spec = remainder if remainder else None
    return name, version_spec, condition


def _to_entries(
    deps: list[str],
    dependency_type: str,
) -> list[DependencyEntry]:
    """Convert string dependencies to normalized entries."""
    result: list[DependencyEntry] = []
    for dep in deps:
        name, version_spec, condition = _split_dependency(dep)
        result.append(
            DependencyEntry(
                name=name,
                version_spec=version_spec,
                condition=condition,
                dependency_type=dependency_type,
            )
        )
    return result


def build_dependency_graph(
    pyproject_path: Path,
    repository: str,
) -> DependencyGraph:
    """Build a normalized dependency graph from ``pyproject.toml``."""
    with open(pyproject_path, "rb") as handle:
        data = _toml_module.load(handle)

    project_data = data.get("project", {})
    metadata = ProjectMetadata(
        name=project_data.get("name", "libp2p"),
        version=project_data.get("version", "unknown"),
        python_version=project_data.get("requires-python", ">=3.10, <4.0"),
        repository=repository,
    )

    dependencies = _to_entries(project_data.get("dependencies", []), "runtime")
    optional_raw = project_data.get("optional-dependencies", {})
    optional_dependencies: dict[str, list[DependencyEntry]] = {}
    for group_name, group_values in optional_raw.items():
        optional_dependencies[group_name] = _to_entries(
            group_values,
            f"optional-{group_name}",
        )

    edges: list[tuple[str, str]] = []
    for dep in dependencies:
        edges.append((metadata.name, dep.name))
    for group_entries in optional_dependencies.values():
        for dep in group_entries:
            edges.append((metadata.name, dep.name))

    return DependencyGraph(
        project=metadata,
        dependencies=dependencies,
        optional_dependencies=optional_dependencies,
        edges=edges,
    )
