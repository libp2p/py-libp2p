#!/usr/bin/env python3
"""Generate transitive dependency graph artifacts for py-libp2p."""

from __future__ import annotations

from pathlib import Path

from libp2p.observability.oso.transitive_graph import (
    generate_transitive_graph_artifacts,
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    artifacts = generate_transitive_graph_artifacts(repo_root=repo_root)
    print("✨ Transitive dependency graph generation complete")
    for kind, path in artifacts.items():
        print(f"- {kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
