"""
Cross-platform path handling utilities for py-libp2p.

This module provides platform-agnostic functions for handling paths,
temporary directories, virtual environments, and binary paths.
"""

import os
import tempfile
from pathlib import Path
from typing import Optional


def get_temp_dir() -> Path:
    """
    Get the platform-appropriate temporary directory.
    
    Returns:
        Path: Path to the system's temporary directory
    """
    return Path(tempfile.gettempdir())


def get_log_file_path(timestamp: str) -> Path:
    """
    Get a platform-agnostic log file path.
    
    Args:
        timestamp: Timestamp string for the log file name
        
    Returns:
        Path: Path to the log file in the system's temp directory
    """
    temp_dir = get_temp_dir()
    return temp_dir / f"{timestamp}_py-libp2p.log"


def get_venv_python(venv_path: Path) -> Path:
    """
    Get the Python executable path for a virtual environment.
    
    Args:
        venv_path: Path to the virtual environment
        
    Returns:
        Path: Path to the Python executable in the virtual environment
    """
    if os.name == 'nt':  # Windows
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def get_venv_pip(venv_path: Path) -> Path:
    """
    Get the pip executable path for a virtual environment.
    
    Args:
        venv_path: Path to the virtual environment
        
    Returns:
        Path: Path to the pip executable in the virtual environment
    """
    if os.name == 'nt':  # Windows
        return venv_path / "Scripts" / "pip.exe"
    return venv_path / "bin" / "pip"


def get_binary_path(env_var: str, binary_name: str, default_path: Optional[Path] = None) -> Path:
    """
    Get a binary path from an environment variable with platform-specific handling.
    
    Args:
        env_var: Environment variable name containing the base path
        binary_name: Name of the binary (without extension)
        default_path: Optional default path if environment variable is not set
        
    Returns:
        Path: Path to the binary
        
    Raises:
        KeyError: If env_var is not set and no default_path is provided
    """
    base_path_str = os.environ.get(env_var)
    if base_path_str is None:
        if default_path is None:
            raise KeyError(f"Environment variable {env_var} is not set")
        base_path = default_path
    else:
        base_path = Path(base_path_str)
    
    # Add .exe extension on Windows
    if os.name == 'nt':
        binary_name = f"{binary_name}.exe"
    
    return base_path / "bin" / binary_name


def get_venv_activate_script(venv_path: Path) -> Path:
    """
    Get the virtual environment activation script path.
    
    Args:
        venv_path: Path to the virtual environment
        
    Returns:
        Path: Path to the activation script
    """
    if os.name == 'nt':  # Windows
        return venv_path / "Scripts" / "activate.bat"
    return venv_path / "bin" / "activate"


def is_windows() -> bool:
    """
    Check if the current platform is Windows.
    
    Returns:
        bool: True if running on Windows, False otherwise
    """
    return os.name == 'nt'


def is_unix_like() -> bool:
    """
    Check if the current platform is Unix-like (Linux, macOS, etc.).
    
    Returns:
        bool: True if running on a Unix-like system, False otherwise
    """
    return os.name != 'nt'


def get_platform_specific_path(base_path: Path, *components: str) -> Path:
    """
    Build a platform-specific path from components.
    
    Args:
        base_path: Base path to start from
        *components: Path components to join
        
    Returns:
        Path: Platform-specific path
    """
    path = base_path
    for component in components:
        path = path / component
    
    # Add .exe extension for executables on Windows if not already present
    if is_windows() and path.suffix == '' and 'bin' in str(path):
        # Check if this looks like an executable path
        if any(executable in str(path) for executable in ['python', 'pip', 'go', 'node']):
            path = path.with_suffix('.exe')
    
    return path 