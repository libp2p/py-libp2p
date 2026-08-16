"""Transitive dependency graph generation helpers."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib as _toml_module
else:
    import tomli as _toml_module  # type: ignore[import]


def get_installed_packages() -> dict[str, str]:
    """Get installed packages and versions from pip."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        return {entry["name"].lower(): entry["version"] for entry in payload}
    except Exception:
        return {}


def get_package_dependencies(package_name: str) -> list[str]:
    """Get direct dependencies of package from `pip show`."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []
    for line in result.stdout.splitlines():
        if line.startswith("Requires:"):
            raw = line.replace("Requires:", "").strip()
            if not raw:
                return []
            return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def build_transitive_graph(
    root_package: str,
    direct_dependencies: list[str],
    max_depth: int = 10,
) -> dict[str, Any]:
    """Build transitive graph by recursively resolving dependencies."""
    installed = get_installed_packages()
    nodes: dict[str, dict[str, Any]] = {root_package: {"type": "project", "depth": 0}}
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def resolve(package: str, depth: int, parent: str) -> None:
        if depth > max_depth or package in seen:
            return
        seen.add(package)
        for dep in get_package_dependencies(package):
            dep_name = dep.split("[")[0].split(";")[0].strip().lower()
            if dep_name == root_package.lower():
                continue
            if dep_name not in nodes:
                nodes[dep_name] = {
                    "type": "dependency",
                    "depth": depth + 1,
                    "installed": dep_name in installed,
                }
                if dep_name in installed:
                    nodes[dep_name]["version"] = installed[dep_name]
            if (parent.lower(), dep_name) not in {
                (edge["from"].lower(), edge["to"].lower()) for edge in edges
            }:
                edges.append({"from": parent, "to": dep_name, "depth": depth})
            resolve(dep_name, depth + 1, dep_name)

    for dep in direct_dependencies:
        dep_name = dep.lower()
        if dep_name not in nodes:
            nodes[dep_name] = {
                "type": "direct_dependency",
                "depth": 1,
                "installed": dep_name in installed,
            }
            if dep_name in installed:
                nodes[dep_name]["version"] = installed[dep_name]
        edges.append({"from": root_package, "to": dep_name, "depth": 0})
        resolve(dep_name, 1, dep_name)

    return {
        "project": {"name": root_package},
        "nodes": [{"id": name, **info} for name, info in nodes.items()],
        "edges": edges,
    }


def _extract_direct_dependency_names(pyproject_path: Path) -> tuple[str, list[str]]:
    with open(pyproject_path, "rb") as handle:
        data = _toml_module.load(handle)
    project = data.get("project", {})
    dependencies = project.get("dependencies", [])
    direct: list[str] = []
    for dep in dependencies:
        dep = dep.split(";")[0].strip()
        if "(" in dep and ")" in dep:
            match = re.match(r"^([a-zA-Z0-9_-]+)\s*\(", dep)
            if match:
                direct.append(match.group(1))
        else:
            parts = re.split(r"([><=!~]+)", dep, maxsplit=1)
            direct.append(parts[0].strip())
    return project.get("name", "libp2p"), direct


def generate_transitive_graph_artifacts(
    repo_root: Path,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Generate transitive dependency artifacts (json/dot/mmd)."""
    pyproject_path = repo_root / "pyproject.toml"
    target_dir = output_dir or (repo_root / "docs" / "dependency_graph")
    target_dir.mkdir(parents=True, exist_ok=True)

    project_name, direct = _extract_direct_dependency_names(pyproject_path)
    graph = build_transitive_graph(project_name, direct)

    json_path = target_dir / "dependencies_transitive.json"
    dot_path = target_dir / "dependencies_transitive.dot"
    mmd_path = target_dir / "dependencies_transitive.mmd"

    json_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

    dot_lines = ["digraph dependencies {", "  rankdir=TB;", "  node [shape=box];", ""]
    for node in graph["nodes"]:
        node_id = node["id"]
        version = node.get("version", "")
        label = node_id if not version else f"{node_id}\\n{version}"
        node_type = node.get("type", "dependency")
        if node_type == "project":
            dot_lines.append(
                f'  "{node_id}" [label="{label}", style=filled, fillcolor=lightblue];'
            )
        elif node_type == "direct_dependency":
            dot_lines.append(
                f'  "{node_id}" [label="{label}", style=filled, fillcolor=lightgreen];'
            )
        else:
            dot_lines.append(f'  "{node_id}" [label="{label}"];')
    dot_lines.append("")
    for edge in graph["edges"]:
        dot_lines.append(f'  "{edge["from"]}" -> "{edge["to"]}";')
    dot_lines.append("}")
    dot_path.write_text("\n".join(dot_lines) + "\n", encoding="utf-8")

    mmd_lines = ["graph TD"]
    for node in graph["nodes"]:
        node_id = node["id"].replace("-", "_").replace(".", "_")
        label = node["id"]
        version = node.get("version", "")
        if version:
            label += f"<br/>{version}"
        mmd_lines.append(f'    {node_id}["{label}"]')
    for edge in graph["edges"]:
        source = edge["from"].replace("-", "_").replace(".", "_")
        target = edge["to"].replace("-", "_").replace(".", "_")
        mmd_lines.append(f"    {source} --> {target}")
    mmd_path.write_text("\n".join(mmd_lines) + "\n", encoding="utf-8")

    return {"json": json_path, "dot": dot_path, "mmd": mmd_path}
