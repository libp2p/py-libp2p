# Contributing to py-libp2p

Welcome to py-libp2p! We appreciate your interest in contributing. This document outlines the guidelines for contributing to the project.

## Commit Message Guidelines

We follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification for commit messages.

### Type

Must be one of the following:

- **ci**: CI configuration (e.g., GitHub Actions)
- **docs**: Documentation
- **feat**: Adding a feature
- **fix**: Fixing a bug
- **perf**: Improvements to performance
- **refactor**: Changes that restructure code but do not change the function
- **test**: Related to tests

### Scope

Scopes should identify the specific component of the project being modified. The following are the supported scopes for py-libp2p:

- **network**: Changes to the core networking logic (e.g., `swarm.py`)
- **peer**: Changes related to peer management (e.g., `peer_id.py`)
- **transport**: Changes to transport implementations (e.g., TCP, WebSockets)
- **protocol**: Changes to protocol negotiation and multiplexing
- **routing**: Changes to peer routing logic
- **security**: Changes to secure communication (e.g., encryption, authentication)
- **stream**: Changes to stream handling for data exchange
- **tests**: Changes to test files or test utilities
- **docs**: Documentation updates
- **examples**: Changes to example code or tutorials
- **tools**: Changes to development tools or scripts

### Examples

- `feat(network): add auto-reconnect to TCP transport`
- `fix(peer): fix peer ID encoding bug`
- `docs(examples): update chat app tutorial`

---

## How to Contribute

### 1. Set Up Your Development Environment
1. **Fork the Repository**: Start by forking the [py-libp2p repository](https://github.com/libp2p/py-libp2p) to your GitHub account.
2. **Clone Your Fork**:
```bash
git clone https://github.com/<your-username>/py-libp2p.git
cd py-libp2p
```
3. Create and activate a virtual environment:
```bash
# On Unix/macOS
python -m venv venv
source venv/bin/activate

# On Windows
python -m venv venv
venv\Scripts\activate
```
4. Install development dependencies:
```bash
pip install -e ".[dev]"
```
5. **Run Tests**:
```bash
pytest
```
Ensure all tests pass before making changes.

### 2. Create a Branch
Create a new branch for your changes:
```bash
git checkout -b my-feature-branch
```

### 3. Make Your Changes
- Write your code and ensure it follows the project's coding standards.
- Add tests for any new functionality or bug fixes.
- Update documentation if necessary.

### 4. Commit Your Changes
Use a descriptive commit message following the Conventional Commits guidelines:
```bash
git add .
git commit -m "feat(network): add auto-reconnect to TCP transport"
```

### 5. Push Your Changes
Push your branch to your forked repository:
```bash
git push origin my-feature-branch
```

### 6. Open a Pull Request
1. Go to the [py-libp2p repository](https://github.com/libp2p/py-libp2p) and click **New Pull Request**.
2. Select your branch and write a clear description of your changes.
3. Reference any related issues (e.g., `Fixes #123`).

---

## Code Review Process
- Your PR will be reviewed by maintainers and other contributors.
- Address any feedback by making additional commits to your branch.
- Once approved, your changes will be merged into the main branch.

---

## Reporting Issues
If you find a bug or have a feature request, please open an issue on the [GitHub Issues page](https://github.com/libp2p/py-libp2p/issues). Include as much detail as possible, including steps to reproduce the issue.

---

## Code of Conduct
Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.

---

Thank you for contributing to py-libp2p! 🚀