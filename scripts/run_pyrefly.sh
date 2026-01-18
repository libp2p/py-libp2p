#!/usr/bin/env bash
# Wrapper script to run pyrefly with the correct Python interpreter
# This ensures pyrefly uses the active virtual environment's Python

# Get the Python executable that's currently active
PYTHON_EXEC="${PYTHON:-python}"

# Try to detect the virtual environment from the Python path
VENV_PATH=""
if command -v "$PYTHON_EXEC" > /dev/null 2>&1; then
    PYTHON_PATH=$(command -v "$PYTHON_EXEC")
    # Check if Python is in a venv (common patterns: */venv*/bin/python, */venv*/Scripts/python)
    # Use case-insensitive pattern matching for better compatibility
    if [[ "$PYTHON_PATH" =~ /venv[^/]*/bin/python ]] || [[ "$PYTHON_PATH" =~ /venv[^/]*/Scripts/python ]]; then
        # Extract venv path and set VIRTUAL_ENV
        # Go up two directories: bin/python -> venv -> project root
        VENV_PATH=$(dirname "$(dirname "$PYTHON_PATH")")
        export VIRTUAL_ENV="$VENV_PATH"
    fi
fi

# Try to use pyrefly command directly (from PATH/venv), fallback to python -m pyrefly
if command -v pyrefly > /dev/null 2>&1; then
    exec pyrefly check "$@"
elif [ -n "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/pyrefly" ]; then
    # Use pyrefly from the detected venv
    exec "$VENV_PATH/bin/pyrefly" check "$@"
else
    # Fallback to python -m pyrefly
    exec "$PYTHON_EXEC" -m pyrefly check "$@"
fi
