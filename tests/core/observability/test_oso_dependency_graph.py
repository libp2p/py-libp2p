from __future__ import annotations

from pathlib import Path

from libp2p.observability.oso.dependency_graph import build_dependency_graph


def test_build_dependency_graph(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "libp2p"
version = "0.0.1"
requires-python = ">=3.10,<4.0"
dependencies = [
  "requests>=2.30.0",
  "zeroconf (>=0.147.0,<0.148.0)",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    graph = build_dependency_graph(
        pyproject_path=pyproject,
        repository="https://github.com/libp2p/py-libp2p",
    )

    assert graph.project.name == "libp2p"
    assert graph.project.version == "0.0.1"
    assert len(graph.dependencies) == 2
    assert graph.dependencies[0].name == "requests"
    assert graph.dependencies[0].version_spec == ">=2.30.0"
    assert graph.dependencies[1].name == "zeroconf"
    assert graph.optional_dependencies["dev"][0].name == "pytest"
    assert ("libp2p", "requests") in graph.edges
