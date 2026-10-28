# OSO Module Architecture

`py-libp2p` uses a module-first observability design:

- **Business logic** lives in `libp2p/observability/oso/`.
- **Operational entry scripts** live in `scripts/oso/` and only delegate to the package.
- **Canonical CLI** is `oso-health-report` from `pyproject.toml`.

## Maintainer Interfaces

- Preferred:
  - `oso-health-report --repo-root . --repo-slug libp2p/py-libp2p`
- Operational wrappers:
  - `python scripts/oso/collect_health_metrics.py --repo-root . --repo-slug libp2p/py-libp2p`
  - `python scripts/oso/integrate_oso.py --repo-root . --repo-slug libp2p/py-libp2p`

## Dependency Graph Interfaces

- `python scripts/oso/generate_dependency_graph.py`
- `python scripts/oso/generate_transitive_dependency_graph.py`
