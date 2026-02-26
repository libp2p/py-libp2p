# Directory Structure Analysis

## Current Layout

- Dependency graph operational scripts are in `scripts/oso/`.
- OSO module logic is in `libp2p/observability/oso/`.
- OSO maintainer docs are in `docs/observability/`.
- Graph-format docs remain in `docs/dependency_graph/`.

## Regeneration Commands

```bash
python3 scripts/oso/generate_dependency_graph.py
python3 scripts/oso/generate_transitive_dependency_graph.py
```

## Notes

- This layout keeps business logic out of script entrypoints.
- Wrapper scripts exist for operational workflows and CI jobs only.
