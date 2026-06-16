# py-ipfs-lite
Python bootstrap for an embeddable IPFS-lite implementation inspired by `go-ipfs-lite`.

## Status
This repository is currently in **Phase 1 (bootstrap)**:
- Packaging and tooling scaffold
- Base Python package skeleton
- Test harness and developer workflows
- Placeholder `examples/` and `interop/` directories

## Quickstart
Install editable package with development dependencies:

```bash
python3 -m pip install -e ".[dev,test]"
```

Run tests:

```bash
python3 -m pytest tests
```

Run lint/type checks:

```bash
python3 -m ruff check .
python3 -m mypy py_ipfs_lite
```

## Planned API parity
See `API_SPEC_GO_IPFS_LITE.txt` for the API contract targeting go-ipfs-lite-style abstractions.

