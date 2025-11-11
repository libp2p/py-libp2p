#!/usr/bin/env python3
"""
Generate a dependency graph for py-libp2p.

This script analyzes the project's dependencies from pyproject.toml and generates
a dependency graph in various formats (JSON, DOT, Mermaid) that can be used with
tools like Open Source Observer (OSO) or other dependency analysis tools.
"""

import json
from pathlib import Path
import re
import sys
from typing import Any

try:
    import tomli
except ImportError:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        print("Error: tomli or tomllib required. Install with: pip install tomli")
        sys.exit(1)
        tomli = None  # type: ignore

# For Python 3.11+, use built-in tomllib
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


def parse_version_spec(spec: str) -> dict[str, Any]:
    """
    Parse a version specification string into components.

    Examples:
        ">=1.2.0" -> {"operator": ">=", "version": "1.2.0"}
        "==21.0.0" -> {"operator": "==", "version": "21.0.0"}
        ">=0.147.0,<0.148.0" -> {
            "operator": "range", "min": "0.147.0", "max": "0.148.0"
        }

    """
    spec = spec.strip()

    # Handle version ranges
    if "," in spec:
        parts = [p.strip() for p in spec.split(",")]
        result = {"operator": "range", "parts": []}
        for part in parts:
            result["parts"].append(parse_version_spec(part))
        return result

    # Match operators: >=, <=, ==, !=, >, <, ~=, ~
    match = re.match(r"^([><=!~]+)\s*(.+)$", spec)
    if match:
        operator, version = match.groups()
        return {"operator": operator, "version": version}

    # No operator, just version
    return {"operator": "==", "version": spec}


def extract_dependencies(pyproject_path: Path) -> dict[str, Any]:
    """Extract dependencies from pyproject.toml."""
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    dependencies = project.get("dependencies", [])
    optional_deps = project.get("optional-dependencies", {})

    # Parse main dependencies
    main_deps = []
    for dep in dependencies:
        if ";" in dep:
            # Handle conditional dependencies
            # (e.g., "package>=1.0; python_version < '3.11'")
            package_part, condition = dep.split(";", 1)
            package_part = package_part.strip()
            condition = condition.strip()
        else:
            package_part = dep.strip()
            condition = None

        # Extract package name and version spec
        # Handle cases like "zeroconf (>=0.147.0,<0.148.0)" with space before paren
        package_part = package_part.strip()
        if "(" in package_part and ")" in package_part:
            # Extract name and version from format like "package (version)"
            match = re.match(r"^([a-zA-Z0-9_-]+)\s*\((.+)\)$", package_part)
            if match:
                name = match.group(1)
                version_spec = match.group(2).strip()
            else:
                # Fallback: try to split on first space
                parts = package_part.split(None, 1)
                name = parts[0]
                version_spec = parts[1] if len(parts) > 1 else None
        elif re.match(r"^[a-zA-Z0-9_-]+", package_part):
            # Simple package name with version spec attached
            parts = re.split(r"([><=!~]+)", package_part, maxsplit=1)
            if len(parts) == 1:
                name = parts[0]
                version_spec = None
            else:
                name = parts[0]
                version_spec = "".join(parts[1:]) if len(parts) > 1 else None
        else:
            # Handle edge cases
            name = package_part
            version_spec = None

        main_deps.append(
            {
                "name": name,
                "version_spec": version_spec,
                "version_parsed": parse_version_spec(version_spec)
                if version_spec
                else None,
                "condition": condition,
                "type": "runtime",
            }
        )

    # Parse optional dependencies
    optional_deps_parsed = {}
    for group_name, group_deps in optional_deps.items():
        optional_deps_parsed[group_name] = []
        for dep in group_deps:
            if ";" in dep:
                package_part, condition = dep.split(";", 1)
                package_part = package_part.strip()
                condition = condition.strip()
            else:
                package_part = dep.strip()
                condition = None

            # Handle cases like "zeroconf (>=0.147.0,<0.148.0)" with space before paren
            package_part = package_part.strip()
            if "(" in package_part and ")" in package_part:
                # Extract name and version from format like "package (version)"
                match = re.match(r"^([a-zA-Z0-9_-]+)\s*\((.+)\)$", package_part)
                if match:
                    name = match.group(1)
                    version_spec = match.group(2).strip()
                else:
                    # Fallback: try to split on first space
                    parts = package_part.split(None, 1)
                    name = parts[0]
                    version_spec = parts[1] if len(parts) > 1 else None
            elif re.match(r"^[a-zA-Z0-9_-]+", package_part):
                parts = re.split(r"([><=!~]+)", package_part, maxsplit=1)
                if len(parts) == 1:
                    name = parts[0]
                    version_spec = None
                else:
                    name = parts[0]
                    version_spec = "".join(parts[1:]) if len(parts) > 1 else None
            else:
                name = package_part
                version_spec = None

            optional_deps_parsed[group_name].append(
                {
                    "name": name,
                    "version_spec": version_spec,
                    "version_parsed": parse_version_spec(version_spec)
                    if version_spec
                    else None,
                    "condition": condition,
                    "type": f"optional-{group_name}",
                }
            )

    return {
        "project": {
            "name": project.get("name", "libp2p"),
            "version": project.get("version", "unknown"),
            "python_version": project.get("requires-python", ">=3.10, <4.0"),
        },
        "dependencies": main_deps,
        "optional_dependencies": optional_deps_parsed,
    }


def generate_json_graph(deps_data: dict[str, Any], output_path: Path) -> None:
    """Generate JSON format dependency graph."""
    graph = {
        "project": deps_data["project"],
        "nodes": [],
        "edges": [],
    }

    # Add project as root node
    graph["nodes"].append(
        {
            "id": deps_data["project"]["name"],
            "type": "project",
            "name": deps_data["project"]["name"],
            "version": deps_data["project"]["version"],
        }
    )

    # Add dependency nodes and edges
    for dep in deps_data["dependencies"]:
        node_id = dep["name"]
        graph["nodes"].append(
            {
                "id": node_id,
                "type": "dependency",
                "name": dep["name"],
                "version_spec": dep["version_spec"],
                "dependency_type": dep["type"],
            }
        )
        graph["edges"].append(
            {
                "from": deps_data["project"]["name"],
                "to": node_id,
                "type": "depends_on",
                "version_spec": dep["version_spec"],
            }
        )

    # Add optional dependencies
    for group_name, group_deps in deps_data["optional_dependencies"].items():
        for dep in group_deps:
            node_id = dep["name"]
            # Check if node already exists
            if not any(n["id"] == node_id for n in graph["nodes"]):
                graph["nodes"].append(
                    {
                        "id": node_id,
                        "type": "dependency",
                        "name": dep["name"],
                        "version_spec": dep["version_spec"],
                        "dependency_type": dep["type"],
                    }
                )
            graph["edges"].append(
                {
                    "from": deps_data["project"]["name"],
                    "to": node_id,
                    "type": "optional_depends_on",
                    "group": group_name,
                    "version_spec": dep["version_spec"],
                }
            )

    with open(output_path, "w") as f:
        json.dump(graph, f, indent=2)

    print(f"✅ Generated JSON graph: {output_path}")


def generate_dot_graph(deps_data: dict[str, Any], output_path: Path) -> None:
    """Generate Graphviz DOT format dependency graph."""
    lines = ["digraph dependencies {"]
    lines.append("  rankdir=LR;")
    lines.append("  node [shape=box];")
    lines.append("")

    # Add project node
    project_name = deps_data["project"]["name"]
    version = deps_data["project"]["version"]
    label = f"{project_name}\\n{version}"
    lines.append(
        f'  "{project_name}" [label="{label}", style=filled, fillcolor=lightblue];'
    )
    lines.append("")

    # Add dependency nodes and edges
    for dep in deps_data["dependencies"]:
        dep_name = dep["name"]
        version_spec = dep["version_spec"] or ""
        label = f"{dep_name}\\n{version_spec}" if version_spec else dep_name
        lines.append(f'  "{dep_name}" [label="{label}"];')
        lines.append(f'  "{project_name}" -> "{dep_name}";')

    # Add optional dependencies
    for group_name, group_deps in deps_data["optional_dependencies"].items():
        for dep in group_deps:
            dep_name = dep["name"]
            version_spec = dep["version_spec"] or ""
            label = f"{dep_name}\\n{version_spec}" if version_spec else dep_name
            if not any(f'"{dep_name}"' in line for line in lines):
                lines.append(f'  "{dep_name}" [label="{label}", style=dashed];')
            edge_label = f'  "{project_name}" -> "{dep_name}"'
            edge_attrs = f'[style=dashed, label="{group_name}"];'
            lines.append(f"{edge_label} {edge_attrs}")

    lines.append("}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    print(f"✅ Generated DOT graph: {output_path}")


def generate_mermaid_graph(deps_data: dict[str, Any], output_path: Path) -> None:
    """Generate Mermaid format dependency graph."""
    lines = ["graph TD"]

    project_name = deps_data["project"]["name"]

    # Add project node
    lines.append(
        f'    {project_name}["{project_name}<br/>{deps_data["project"]["version"]}"]'
    )

    # Add dependency nodes and edges
    for dep in deps_data["dependencies"]:
        dep_name = dep["name"].replace("-", "_").replace(".", "_")
        version_spec = dep["version_spec"] or ""
        label = f"{dep['name']}<br/>{version_spec}" if version_spec else dep["name"]
        lines.append(f'    {dep_name}["{label}"]')
        lines.append(f"    {project_name} --> {dep_name}")

    # Add optional dependencies
    for group_name, group_deps in deps_data["optional_dependencies"].items():
        for dep in group_deps:
            dep_name = dep["name"].replace("-", "_").replace(".", "_")
            version_spec = dep["version_spec"] or ""
            label = f"{dep['name']}<br/>{version_spec}" if version_spec else dep["name"]
            if not any(f"{dep_name}[" in line for line in lines):
                lines.append(f'    {dep_name}["{label}"]')
            lines.append(f'    {project_name} -.->|"{group_name}"| {dep_name}')

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    print(f"✅ Generated Mermaid graph: {output_path}")


def generate_summary(deps_data: dict[str, Any], output_path: Path) -> None:
    """Generate a human-readable summary of dependencies."""
    lines = []
    lines.append("# py-libp2p Dependency Graph")
    lines.append("")
    project_name = deps_data["project"]["name"]
    project_version = deps_data["project"]["version"]
    lines.append(f"**Project**: {project_name} v{project_version}")
    lines.append(f"**Python Version**: {deps_data['project']['python_version']}")
    lines.append("")

    lines.append("## Runtime Dependencies")
    lines.append("")
    lines.append(f"Total: {len(deps_data['dependencies'])} dependencies")
    lines.append("")
    for dep in sorted(deps_data["dependencies"], key=lambda x: x["name"].lower()):
        version_info = f" ({dep['version_spec']})" if dep["version_spec"] else ""
        condition_info = f" [{dep['condition']}]" if dep["condition"] else ""
        lines.append(f"- **{dep['name']}**{version_info}{condition_info}")

    lines.append("")
    lines.append("## Optional Dependencies")
    lines.append("")
    for group_name, group_deps in sorted(deps_data["optional_dependencies"].items()):
        lines.append(f"### {group_name.title()} ({len(group_deps)} dependencies)")
        lines.append("")
        for dep in sorted(group_deps, key=lambda x: x["name"].lower()):
            version_info = f" ({dep['version_spec']})" if dep["version_spec"] else ""
            condition_info = f" [{dep['condition']}]" if dep["condition"] else ""
            lines.append(f"- **{dep['name']}**{version_info}{condition_info}")
        lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    print(f"✅ Generated summary: {output_path}")


def main():
    """Main function to generate dependency graphs."""
    repo_root = Path(__file__).parent.parent
    pyproject_path = repo_root / "pyproject.toml"
    output_dir = repo_root / "docs" / "dependency_graph"

    if not pyproject_path.exists():
        print(f"Error: {pyproject_path} not found")
        sys.exit(1)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    print("📦 Analyzing dependencies from pyproject.toml...")
    deps_data = extract_dependencies(pyproject_path)

    print(f"   Found {len(deps_data['dependencies'])} runtime dependencies")
    total_optional = sum(
        len(deps) for deps in deps_data["optional_dependencies"].values()
    )
    print(f"   Found {total_optional} optional dependencies")
    print("")

    # Generate different formats
    generate_json_graph(deps_data, output_dir / "dependencies.json")
    generate_dot_graph(deps_data, output_dir / "dependencies.dot")
    generate_mermaid_graph(deps_data, output_dir / "dependencies.mmd")
    generate_summary(deps_data, output_dir / "dependencies.md")

    print("")
    print("✨ Dependency graph generation complete!")
    print(f"   Output directory: {output_dir}")


if __name__ == "__main__":
    main()
