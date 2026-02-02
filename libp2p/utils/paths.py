"""
Cross-platform path utilities for py-libp2p.

This module provides standardized path operations to ensure consistent
behavior across Windows, macOS, and Linux platforms.
"""

import os
from pathlib import Path
import sys
import tempfile
from typing import Union

PathLike = Union[str, Path]

ED25519_PATH = Path("libp2p-forge/peer1/ed25519.pem")
AUTOTLS_CERT_PATH = Path("libp2p-forge/peer1/autotls-cert.pem")
AUTOTLS_KEY_PATH = Path("libp2p-forge/peer1/autotls-key.pem")


def get_temp_dir() -> Path:
    """
    Get cross-platform temporary directory.

    Returns:
        Path: Platform-specific temporary directory path

    """
    return Path(tempfile.gettempdir())


def get_project_root() -> Path:
    """
    Get the project root directory.

    Returns:
        Path: Path to the py-libp2p project root

    """
    # Navigate from libp2p/utils/paths.py to project root
    return Path(__file__).parent.parent.parent


def join_paths(*parts: PathLike) -> Path:
    """
    Cross-platform path joining.

    Args:
        *parts: Path components to join

    Returns:
        Path: Joined path using platform-appropriate separator

    """
    return Path(*parts)


def ensure_dir_exists(path: PathLike) -> Path:
    """
    Ensure directory exists, create if needed.

    Args:
        path: Directory path to ensure exists

    Returns:
        Path: Path object for the directory

    """
    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return path_obj


def get_config_dir() -> Path:
    """
    Get user config directory (cross-platform).

    Returns:
        Path: Platform-specific config directory

    """
    if os.name == "nt":  # Windows
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "py-libp2p"
        else:
            # Fallback to user home directory
            return Path.home() / "AppData" / "Roaming" / "py-libp2p"
    else:  # Unix-like (Linux, macOS)
        return Path.home() / ".config" / "py-libp2p"


def get_script_dir(script_path: PathLike | None = None) -> Path:
    """
    Get the directory containing a script file.

    Args:
        script_path: Path to the script file. If None, uses __file__

    Returns:
        Path: Directory containing the script

    Raises:
        RuntimeError: If script path cannot be determined

    """
    if script_path is None:
        # This will be the directory of the calling script
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            script_path = frame.f_back.f_globals.get("__file__")
        else:
            raise RuntimeError("Could not determine script path")

    if script_path is None:
        raise RuntimeError("Script path is None")

    return Path(script_path).parent.absolute()


def create_temp_file(prefix: str = "py-libp2p_", suffix: str = ".log") -> Path:
    """
    Create a temporary file with a unique name.

    Args:
        prefix: File name prefix
        suffix: File name suffix

    Returns:
        Path: Path to the created temporary file

    """
    temp_dir = get_temp_dir()
    # Create a unique filename using timestamp and random bytes
    import secrets
    import time

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    microseconds = f"{time.time() % 1:.6f}"[2:]  # Get microseconds as string
    unique_id = secrets.token_hex(4)
    filename = f"{prefix}{timestamp}_{microseconds}_{unique_id}{suffix}"

    temp_file = temp_dir / filename
    # Create the file by touching it
    temp_file.touch()
    return temp_file


def resolve_relative_path(base_path: PathLike, relative_path: PathLike) -> Path:
    """
    Resolve a relative path from a base path.

    Args:
        base_path: Base directory path
        relative_path: Relative path to resolve

    Returns:
        Path: Resolved absolute path

    """
    base = Path(base_path).resolve()
    relative = Path(relative_path)

    if relative.is_absolute():
        return relative
    else:
        return (base / relative).resolve()


def normalize_path(path: PathLike) -> Path:
    """
    Normalize a path, resolving any symbolic links and relative components.

    Args:
        path: Path to normalize

    Returns:
        Path: Normalized absolute path

    """
    return Path(path).resolve()


def get_venv_path() -> Path | None:
    """
    Get virtual environment path if active.

    Returns:
        Path: Virtual environment path if active, None otherwise

    """
    venv_path = os.environ.get("VIRTUAL_ENV")
    if venv_path:
        return Path(venv_path)
    return None


def get_python_executable() -> Path:
    """
    Get current Python executable path.

    Returns:
        Path: Path to the current Python executable

    """
    return Path(sys.executable)


def find_executable(name: str) -> Path | None:
    """
    Find executable in system PATH.

    Args:
        name: Name of the executable to find

    Returns:
        Path: Path to executable if found, None otherwise

    """
    # Check if name already contains path
    if os.path.dirname(name):
        path = Path(name)
        if path.exists() and os.access(path, os.X_OK):
            return path
        return None

    # Search in PATH
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        if not path_dir:
            continue
        path = Path(path_dir) / name
        if path.exists() and os.access(path, os.X_OK):
            return path

    return None


def get_script_binary_path() -> Path:
    """
    Get path to script's binary directory.

    Returns:
        Path: Directory containing the script's binary

    """
    return get_python_executable().parent


def get_binary_path(binary_name: str) -> Path | None:
    """
    Find binary in PATH or virtual environment.

    Args:
        binary_name: Name of the binary to find

    Returns:
        Path: Path to binary if found, None otherwise

    """
    # First check in virtual environment if active
    venv_path = get_venv_path()
    if venv_path:
        venv_bin = venv_path / "bin" if os.name != "nt" else venv_path / "Scripts"
        binary_path = venv_bin / binary_name
        if binary_path.exists() and os.access(binary_path, os.X_OK):
            return binary_path

    # Fall back to system PATH
    return find_executable(binary_name)
