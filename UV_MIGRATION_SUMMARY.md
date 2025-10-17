# Migration to uv in CI/CD

This document summarizes the changes made to migrate the py-libp2p CI/CD pipeline from pip to uv.

## Changes Made

### 1. GitHub Actions Workflow (`.github/workflows/tox.yml`)

**Added uv installation:**

- Added `astral-sh/setup-uv@v4` action to install uv in both Linux and Windows jobs
- Updated pip commands to use `uv pip` instead of `python -m pip`

**Before:**

```yaml
- run: |
    python -m pip install --upgrade pip
    python -m pip install tox
```

**After:**

```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v4
  with:
    version: "latest"

- run: |
    uv pip install --upgrade pip
    uv pip install tox
```

### 2. Tox Configuration (`tox.ini`)

**Updated wheel test environments:**

- Changed pip commands to use `uv pip` in both Linux and Windows wheel test environments

**Before:**

```ini
commands=
    python -m pip install --upgrade pip
    /bin/bash -c 'python -m pip install --upgrade "$(ls dist/libp2p-*-py3-none-any.whl)" --progress-bar off'
```

**After:**

```ini
commands=
    uv pip install --upgrade pip
    /bin/bash -c 'uv pip install --upgrade "$(ls dist/libp2p-*-py3-none-any.whl)" --progress-bar off'
```

### 3. Package Test Script (`scripts/release/test_package.py`)

**Updated virtual environment creation and package installation:**

- Changed pip commands to use `uv pip` for package installation

**Before:**

```python
subprocess.run(
    [venv_path / "bin" / "pip", "install", "-U", "pip", "setuptools"], check=True
)
```

**After:**

```python
subprocess.run(
    [venv_path / "bin" / "uv", "pip", "install", "-U", "pip", "setuptools"], check=True
)
```

## Benefits of Using uv

1. **Faster Installation**: uv is significantly faster than pip for package installation
1. **Better Dependency Resolution**: More reliable dependency resolution algorithm
1. **Consistent Environment**: Better handling of virtual environments
1. **Modern Tooling**: Built for modern Python development workflows

## Testing

The changes have been tested to ensure:

- ✅ uv is properly installed in CI environments
- ✅ All pip commands have been replaced with `uv pip`
- ✅ No linting errors introduced
- ✅ tox configuration works with uv
- ✅ Package test script works with uv

## Usage

The CI/CD pipeline will now use uv for all package management operations while maintaining the same functionality as before. Developers can continue using the same commands locally, but with improved performance when using uv.
