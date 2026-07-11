# Contributing to py-ipfs-lite

First off, thank you for considering contributing to `py-ipfs-lite`.

## Development Setup

We use `uv` for dependency management and fast environment resolution.

1. **Clone the repository:**

   ```bash
   git clone https://github.com/IPFS-Meshkit/py-ipfs-lite.git
   cd py-ipfs-lite
   ```

1. **Install dependencies:**

   ```bash
   uv sync
   ```

   This will create a virtual environment (`.venv`) and install all package dependencies and development tools.

1. **Run the tests:**

   ```bash
   uv run pytest
   ```

## Code Style

We use `ruff` for fast linting and formatting, and `mypy` for static type checking. Both are wired into our `tox` configuration.

To check your code before committing:

```bash
uv run ruff check .
uv run ruff format .
uv run mypy .
```

Or just run the full `tox` suite:

```bash
uv run tox
```

## Pull Request Expectations

Our house standard is simple: **new features and bug fixes should come with a test that would have caught the bug.**

If you are fixing a concurrency issue, write a test that reliably fails under concurrency before your fix. If you are fixing a protocol issue (like IPNS forgery), include an adversarial test that proves the vulnerability is closed. This standard is what keeps `py-ipfs-lite` stable.

## Where Things Live

If you're trying to figure out where to make your change, start by reading the [Architecture Document](docs/architecture.md). It explains:

- The component model (`Peer` as orchestrator)
- The Adapter pattern used to interface with `py-libp2p`
- How data flows through the system for adding and fetching content
- The concurrency model (`RWLock`)
