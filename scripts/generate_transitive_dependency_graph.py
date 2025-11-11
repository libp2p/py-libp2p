#!/usr/bin/env python3
"""
Generate a FULL transitive dependency graph for py-libp2p.

This script analyzes the project's dependencies from pyproject.toml AND resolves
all transitive dependencies (dependencies of dependencies) to show the complete
dependency tree with interconnections.

Requires: pip install pipdeptree
"""

from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        print("Error: tomli or tomllib required. Install with: pip install tomli")
        sys.exit(1)

# For Python 3.11+, use built-in tomllib
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


def get_installed_packages() -> dict[str, str]:
    """Get all installed packages and their versions."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            check=True,
        )
        packages = json.loads(result.stdout)
        return {pkg["name"].lower(): pkg["version"] for pkg in packages}
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Warning: Could not get installed packages: {e}")
        return {}


def get_package_dependencies(package_name: str) -> list[str]:
    """Get direct dependencies of a package using pip show."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name],
            capture_output=True,
            text=True,
            check=True,
        )
        requires_line = None
        for line in result.stdout.split("\n"):
            if line.startswith("Requires:"):
                requires_line = line.replace("Requires:", "").strip()
                break

        if requires_line:
            # Split by comma and clean up
            deps = [dep.strip() for dep in requires_line.split(",") if dep.strip()]
            return deps
        return []
    except subprocess.CalledProcessError:
        # Package not installed or not found
        return []


def build_transitive_graph(
    root_package: str, direct_deps: list[str], max_depth: int = 10
) -> dict[str, Any]:
    """
    Build a transitive dependency graph by recursively resolving dependencies.

    Args:
        root_package: The root package name (e.g., "libp2p")
        direct_deps: List of direct dependency names
        max_depth: Maximum recursion depth to prevent infinite loops

    """
    nodes = {root_package: {"type": "project", "depth": 0}}
    edges = []
    visited = set()
    installed_packages = get_installed_packages()

    def resolve_deps(package: str, depth: int, parent: str):
        """Recursively resolve dependencies."""
        if depth > max_depth or package in visited:
            return

        visited.add(package)

        # Get package dependencies
        deps = get_package_dependencies(package)

        for dep in deps:
            # Normalize package name (lowercase, handle extras)
            dep_name = dep.split("[")[0].split(";")[0].strip().lower()

            # Skip if it's the root package or already processed at this depth
            if dep_name == root_package.lower():
                continue

            # Add node if not exists
            if dep_name not in nodes:
                nodes[dep_name] = {
                    "type": "dependency",
                    "depth": depth + 1,
                    "installed": dep_name in installed_packages,
                }
                if dep_name in installed_packages:
                    nodes[dep_name]["version"] = installed_packages[dep_name]

            # Add edge
            edge_key = (parent.lower(), dep_name)
            if edge_key not in [(e["from"].lower(), e["to"].lower()) for e in edges]:
                edges.append(
                    {
                        "from": parent,
                        "to": dep_name,
                        "depth": depth,
                    }
                )

            # Recursively resolve this dependency
            if depth < max_depth:
                resolve_deps(dep_name, depth + 1, dep_name)

    # Resolve direct dependencies
    for dep in direct_deps:
        dep_name = dep.lower()
        if dep_name not in nodes:
            nodes[dep_name] = {
                "type": "direct_dependency",
                "depth": 1,
                "installed": dep_name in installed_packages,
            }
            if dep_name in installed_packages:
                nodes[dep_name]["version"] = installed_packages[dep_name]

        edges.append(
            {
                "from": root_package,
                "to": dep_name,
                "depth": 0,
            }
        )

        # Resolve transitive dependencies
        resolve_deps(dep_name, 1, dep_name)

    return {
        "project": {"name": root_package},
        "nodes": [{"id": name, **info} for name, info in nodes.items()],
        "edges": edges,
    }


def generate_json_graph(graph_data: dict[str, Any], output_path: Path) -> None:
    """Generate JSON format dependency graph."""
    with open(output_path, "w") as f:
        json.dump(graph_data, f, indent=2)
    print(f"✅ Generated JSON graph: {output_path}")


def generate_dot_graph(graph_data: dict[str, Any], output_path: Path) -> None:
    """Generate Graphviz DOT format dependency graph."""
    lines = ["digraph dependencies {"]
    lines.append("  rankdir=TB;")
    lines.append("  node [shape=box];")
    lines.append("")

    # Group nodes by depth for better layout
    nodes_by_depth = defaultdict(list)
    for node in graph_data["nodes"]:
        depth = node.get("depth", 0)
        nodes_by_depth[depth].append(node)

    # Add nodes with colors based on type
    for node in graph_data["nodes"]:
        node_id = node["id"]
        node_type = node.get("type", "dependency")
        version = node.get("version", "")
        label = f"{node_id}"
        if version:
            label += f"\\n{version}"

        if node_type == "project":
            lines.append(
                f'  "{node_id}" [label="{label}", style=filled, fillcolor=lightblue];'
            )
        elif node_type == "direct_dependency":
            lines.append(
                f'  "{node_id}" [label="{label}", style=filled, fillcolor=lightgreen];'
            )
        else:
            lines.append(f'  "{node_id}" [label="{label}"];')

    lines.append("")

    # Add edges
    for edge in graph_data["edges"]:
        lines.append(f'  "{edge["from"]}" -> "{edge["to"]}";')

    lines.append("}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    print(f"✅ Generated DOT graph: {output_path}")


def generate_mermaid_graph(graph_data: dict[str, Any], output_path: Path) -> None:
    """Generate Mermaid format dependency graph."""
    lines = ["graph TD"]

    # Add nodes
    for node in graph_data["nodes"]:
        node_id = node["id"].replace("-", "_").replace(".", "_")
        node_type = node.get("type", "dependency")
        version = node.get("version", "")
        label = node["id"]
        if version:
            label += f"<br/>{version}"

        if node_type == "project":
            lines.append(f'    {node_id}["{label}"]:::project')
        elif node_type == "direct_dependency":
            lines.append(f'    {node_id}["{label}"]:::direct')
        else:
            lines.append(f'    {node_id}["{label}"]')

    # Add edges
    for edge in graph_data["edges"]:
        from_id = edge["from"].replace("-", "_").replace(".", "_")
        to_id = edge["to"].replace("-", "_").replace(".", "_")
        lines.append(f"    {from_id} --> {to_id}")

    # Add styling
    lines.append("")
    lines.append("    classDef project fill:#e1f5ff,stroke:#01579b,stroke-width:3px")
    lines.append("    classDef direct fill:#c8e6c9,stroke:#2e7d32,stroke-width:2px")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    print(f"✅ Generated Mermaid graph: {output_path}")


def main():
    """Main function to generate transitive dependency graphs."""
    repo_root = Path(__file__).parent.parent
    pyproject_path = repo_root / "pyproject.toml"
    output_dir = repo_root / "docs" / "dependency_graph"

    if not pyproject_path.exists():
        print(f"Error: {pyproject_path} not found")
        sys.exit(1)

    # Check if pipdeptree is available (optional, we'll use pip show as fallback)
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "show", "pipdeptree"],
            capture_output=True,
            check=True,
        )
        print("📦 Using pip show to resolve dependencies...")
    except subprocess.CalledProcessError:
        print("⚠️  Note: For better results, install pipdeptree: pip install pipdeptree")

    # Read pyproject.toml to get direct dependencies
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    dependencies = project.get("dependencies", [])

    # Extract package names from dependencies
    import re

    direct_deps = []
    for dep in dependencies:
        # Extract package name (handle version specs and conditions)
        dep = dep.split(";")[0].strip()  # Remove conditions
        if "(" in dep and ")" in dep:
            match = re.match(r"^([a-zA-Z0-9_-]+)\s*\(", dep)
            if match:
                direct_deps.append(match.group(1))
        else:
            parts = re.split(r"([><=!~]+)", dep, maxsplit=1)
            direct_deps.append(parts[0].strip())

    project_name = project.get("name", "libp2p")

    print(f"📦 Building transitive dependency graph for {project_name}...")
    print(f"   Direct dependencies: {len(direct_deps)}")
    print("   Resolving transitive dependencies (this may take a moment)...")

    graph_data = build_transitive_graph(project_name, direct_deps)

    print(f"   Total nodes: {len(graph_data['nodes'])}")
    print(f"   Total edges: {len(graph_data['edges'])}")
    print("")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate different formats
    generate_json_graph(graph_data, output_dir / "dependencies_transitive.json")
    generate_dot_graph(graph_data, output_dir / "dependencies_transitive.dot")
    generate_mermaid_graph(graph_data, output_dir / "dependencies_transitive.mmd")

    print("")
    print("✨ Transitive dependency graph generation complete!")
    print(f"   Output directory: {output_dir}")
    print("")
    print("💡 Tip: Generate images with:")
    print("   dot -Tpng dependencies_transitive.dot -o dependencies_transitive.png")
    print("   dot -Tsvg dependencies_transitive.dot -o dependencies_transitive.svg")


if __name__ == "__main__":
    main()
