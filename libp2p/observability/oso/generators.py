"""Dependency graph artifact generators used by operational scripts."""

from __future__ import annotations

import json
from pathlib import Path

from .dependency_graph import build_dependency_graph


def _write_json(data: object, output_path: Path) -> None:
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def generate_direct_graph_artifacts(
    repo_root: Path,
    output_dir: Path | None = None,
    repository: str = "https://github.com/libp2p/py-libp2p",
) -> dict[str, Path]:
    """Generate direct dependency artifacts (json/dot/mmd/md)."""
    pyproject_path = repo_root / "pyproject.toml"
    target_dir = output_dir or (repo_root / "docs" / "dependency_graph")
    target_dir.mkdir(parents=True, exist_ok=True)

    graph = build_dependency_graph(pyproject_path=pyproject_path, repository=repository)

    nodes: list[dict[str, object]] = [
        {
            "id": graph.project.name,
            "type": "project",
            "name": graph.project.name,
            "version": graph.project.version,
        }
    ]
    for dep in graph.dependencies:
        nodes.append(
            {
                "id": dep.name,
                "type": "dependency",
                "name": dep.name,
                "version_spec": dep.version_spec,
                "dependency_type": dep.dependency_type,
            }
        )
    for dep_group in graph.optional_dependencies.values():
        for dep in dep_group:
            if dep.name not in {node["id"] for node in nodes}:
                nodes.append(
                    {
                        "id": dep.name,
                        "type": "dependency",
                        "name": dep.name,
                        "version_spec": dep.version_spec,
                        "dependency_type": dep.dependency_type,
                    }
                )

    json_graph = {
        "project": {
            "name": graph.project.name,
            "version": graph.project.version,
            "python_version": graph.project.python_version,
        },
        "nodes": nodes,
        "edges": [
            {"from": edge_from, "to": edge_to, "type": "depends_on"}
            for edge_from, edge_to in graph.edges
        ],
    }

    json_path = target_dir / "dependencies.json"
    dot_path = target_dir / "dependencies.dot"
    mmd_path = target_dir / "dependencies.mmd"
    md_path = target_dir / "dependencies.md"

    _write_json(json_graph, json_path)

    dot_lines = [
        "digraph dependencies {",
        "  rankdir=LR;",
        '  "libp2p" [shape=box, style=filled, fillcolor=lightblue];',
    ]
    for dep in graph.dependencies:
        dot_lines.append(f'  "{graph.project.name}" -> "{dep.name}";')
    for group, group_deps in graph.optional_dependencies.items():
        for dep in group_deps:
            edge = (
                f'  "{graph.project.name}" -> "{dep.name}" '
                f'[style=dashed, label="{group}"];'
            )
            dot_lines.append(edge)
    dot_lines.append("}")
    dot_path.write_text("\n".join(dot_lines) + "\n", encoding="utf-8")

    mmd_lines = [
        "graph TD",
        (
            f'    {graph.project.name}["{graph.project.name}'
            f'<br/>{graph.project.version}"]'
        ),
    ]
    for dep in graph.dependencies:
        dep_id = dep.name.replace("-", "_").replace(".", "_")
        mmd_lines.append(f'    {dep_id}["{dep.name}"]')
        mmd_lines.append(f"    {graph.project.name} --> {dep_id}")
    for group, group_deps in graph.optional_dependencies.items():
        for dep in group_deps:
            dep_id = dep.name.replace("-", "_").replace(".", "_")
            mmd_lines.append(f'    {graph.project.name} -.->|"{group}"| {dep_id}')
    mmd_path.write_text("\n".join(mmd_lines) + "\n", encoding="utf-8")

    summary_lines = [
        "# py-libp2p Dependency Graph",
        "",
        f"**Project**: {graph.project.name} v{graph.project.version}",
        f"**Python Version**: {graph.project.python_version}",
        "",
        "## Runtime Dependencies",
        "",
        f"Total: {len(graph.dependencies)} dependencies",
        "",
    ]
    for dep in sorted(graph.dependencies, key=lambda item: item.name.lower()):
        version = f" ({dep.version_spec})" if dep.version_spec else ""
        condition = f" [{dep.condition}]" if dep.condition else ""
        summary_lines.append(f"- **{dep.name}**{version}{condition}")
    summary_lines.extend(["", "## Optional Dependencies", ""])
    for group, group_deps in sorted(graph.optional_dependencies.items()):
        summary_lines.append(f"### {group.title()} ({len(group_deps)} dependencies)")
        summary_lines.append("")
        for dep in sorted(group_deps, key=lambda item: item.name.lower()):
            version = f" ({dep.version_spec})" if dep.version_spec else ""
            condition = f" [{dep.condition}]" if dep.condition else ""
            summary_lines.append(f"- **{dep.name}**{version}{condition}")
        summary_lines.append("")
    md_path.write_text("\n".join(summary_lines), encoding="utf-8")

    return {"json": json_path, "dot": dot_path, "mmd": mmd_path, "md": md_path}
