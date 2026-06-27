# Static Lint & Tests Analysis in `py-libp2p`

This document provides a deep dive into the static linting, formatting, and type-checking pipelines configured in the `py-libp2p` project.

## Overview

`py-libp2p` relies heavily on `pre-commit` hooks for its static checks. These checks are primarily orchestrated via a `Makefile` which exposes convenient targets for developers, such as `make lint`, `make fix`, `make typecheck`, and `make pr`.

## 1. Makefile Targets

The `Makefile` serves as the primary entry point for developers to run static analysis:

- **`make fix`**: 
  Runs `python -m ruff check --fix` directly. This uses Ruff to automatically fix all safe auto-fixable linting and formatting issues (such as `isort` sorting and `flake8` auto-fixes).
- **`make lint`**: 
  Executes `pre-commit run --all-files --show-diff-on-failure`. This runs the entire suite of configured pre-commit hooks over all files. If it fails, it prints a helpful message indicating that `pre-commit` might have automatically fixed some issues, and immediately re-runs it to see if the auto-fixes resolved everything.
- **`make typecheck`**: 
  Specifically triggers the type-checking hooks defined in the pre-commit configuration: `pre-commit run mypy-local --all-files` and `pre-commit run pyrefly-local --all-files`.
- **`make pr`**: 
  The comprehensive command to prepare for a Pull Request. It runs `clean`, `fix`, `lint`, `typecheck`, and `test` sequentially. It essentially runs the entire validation pipeline to ensure no checks will fail on CI.

## 2. Pre-commit Configuration (`.pre-commit-config.yaml`)

The `.pre-commit-config.yaml` file defines the hooks that run during `make lint`:

1. **Standard pre-commit-hooks**:
   - `check-yaml` & `check-toml`: Ensures structural validity of configuration files.
   - `end-of-file-fixer`: Ensures files end with a newline.
   - `trailing-whitespace`: Trims trailing whitespace from lines.
2. **`pyupgrade`** (`v3.20.0`): 
   Enforces Python 3.10+ syntax standards (`--py310-plus` argument), automatically upgrading outdated syntax constructs.
3. **Ruff (Linter & Formatter)** (`v0.11.10`):
   - `ruff`: The core linter hook, configured to auto-fix (`--fix`).
   - `ruff-format`: The code formatter hook (a highly compatible and fast alternative to Black).
4. **`mdformat`** (`v0.7.22`):
   Formats Markdown files automatically, coupled with the `mdformat-gfm` dependency to ensure GitHub Flavored Markdown compatibility.
5. **Type Checking (Local Hooks)**:
   - **`mypy-local`**: Runs `mypy -p libp2p` in the local system environment. It relies on the environment having all `dev` dependencies installed.
   - **`pyrefly-local`**: Runs `pyrefly check` in the local system environment for additional type validation.
6. **Custom Local Hooks**:
   - **`check-rst-files`**: A custom python snippet that glob-searches for `.rst` files in the top-level directory and fails if any are found (restricting the repository to markdown files).
   - **`path-audit`**: Runs a cross-platform path handling audit via `python scripts/audit_paths.py --summary-only --fail-on-p1`. This catches hardcoded paths or OS-dependent path handling that would break compatibility.

## 3. Tool Configurations (`pyproject.toml` and `tox.ini`)

The behavior of the above tools is intricately configured in the project settings:

### Ruff Configuration
Ruff's settings in `pyproject.toml` are configured with a line-length of 88. 
- It selects multiple rule sets: `F` (Pyflakes), `E` (pycodestyle errors), `W` (pycodestyle warnings), `I` (isort), and `D` (pydocstyle).
- It explicitly ignores several strict pydocstyle (`D`) rules like `D100` (missing docstring in public module), `D101`, `D205`, etc.
- `isort` settings inside Ruff are configured to recognize `libp2p` and `tests` as first-party modules, and enforce specific sorting for third-party libraries.

### Mypy Configuration
`mypy` is configured strictly in `pyproject.toml`:
- Missing imports are ignored (`ignore_missing_imports = true`).
- Strictly enforces typing for defs (`check_untyped_defs = true`, `disallow_untyped_defs = true`, `disallow_untyped_calls = true`).
- Disallows `Any` generics (`disallow_any_generics = true`).
- Incremental mode is disabled (`incremental = false`) ensuring a full, clean type-check on each run.

### Pyrefly Configuration
`pyrefly` is configured in `pyproject.toml` to include `libp2p`, `examples`, and `tests` while explicitly excluding protobuf generated files (`**/*pb2.py`), virtual environments, and specific test directories (`./tests/interop/nim_libp2p`).

### Tox Integration
In `tox.ini`, there are explicit `lint` environments (e.g., `py{310,311,312,313}-lint`) which install `pre-commit` and run `pre-commit run --all-files --show-diff-on-failure`. This allows CI environments to cleanly execute the exact same linting pipeline across multiple python versions in isolated virtual environments. There is also a legacy `[flake8]` configuration block in `tox.ini` with standard configurations (line length 88, ignore E203), although Ruff now supersedes it.

## Conclusion

`py-libp2p` employs a modern, rigorous, and fast static analysis pipeline centered around **Ruff** (for linting/formatting) and **pre-commit** (for orchestrating hooks). Developers have clear, well-defined entry points via the `Makefile` (`make pr`, `make lint`) that guarantee their code complies with the project's strict syntax (Python 3.10+ via `pyupgrade`), typing (via `mypy` and `pyrefly`), and structural rules (path-audit and RST checks) before any PR is submitted.
