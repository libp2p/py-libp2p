"""
Tests for cross-platform path handling utilities.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from libp2p.utils.paths import (
    get_binary_path,
    get_log_file_path,
    get_platform_specific_path,
    get_temp_dir,
    get_venv_activate_script,
    get_venv_pip,
    get_venv_python,
    is_unix_like,
    is_windows,
)


class TestPathUtilities:
    """Test the cross-platform path handling utilities."""

    def test_get_temp_dir(self):
        """Test that get_temp_dir returns a valid temporary directory."""
        temp_dir = get_temp_dir()
        assert isinstance(temp_dir, Path)
        assert temp_dir.exists()
        assert temp_dir.is_dir()

    def test_get_log_file_path(self):
        """Test that get_log_file_path creates proper log file paths."""
        timestamp = "20240101_120000"
        log_path = get_log_file_path(timestamp)
        
        assert isinstance(log_path, Path)
        assert log_path.name == f"{timestamp}_py-libp2p.log"
        assert log_path.parent == get_temp_dir()

    def test_get_venv_python_windows(self):
        """Test virtual environment Python path on Windows."""
        with patch('os.name', 'nt'):
            venv_path = Path("test_venv")
            python_path = get_venv_python(venv_path)
            expected_path = venv_path / "Scripts" / "python.exe"
            assert python_path == expected_path

    def test_get_venv_python_unix(self):
        """Test virtual environment Python path on Unix-like systems."""
        with patch('os.name', 'posix'):
            venv_path = Path("test_venv")
            python_path = get_venv_python(venv_path)
            expected_path = venv_path / "bin" / "python"
            assert python_path == expected_path

    def test_get_venv_pip_windows(self):
        """Test virtual environment pip path on Windows."""
        with patch('os.name', 'nt'):
            venv_path = Path("test_venv")
            pip_path = get_venv_pip(venv_path)
            expected_path = venv_path / "Scripts" / "pip.exe"
            assert pip_path == expected_path

    def test_get_venv_pip_unix(self):
        """Test virtual environment pip path on Unix-like systems."""
        with patch('os.name', 'posix'):
            venv_path = Path("test_venv")
            pip_path = get_venv_pip(venv_path)
            expected_path = venv_path / "bin" / "pip"
            assert pip_path == expected_path

    def test_get_venv_activate_script_windows(self):
        """Test virtual environment activation script path on Windows."""
        with patch('os.name', 'nt'):
            venv_path = Path("test_venv")
            activate_path = get_venv_activate_script(venv_path)
            expected_path = venv_path / "Scripts" / "activate.bat"
            assert activate_path == expected_path

    def test_get_venv_activate_script_unix(self):
        """Test virtual environment activation script path on Unix-like systems."""
        with patch('os.name', 'posix'):
            venv_path = Path("test_venv")
            activate_path = get_venv_activate_script(venv_path)
            expected_path = venv_path / "bin" / "activate"
            assert activate_path == expected_path

    def test_get_binary_path_with_env_var(self):
        """Test getting binary path with environment variable set."""
        with patch.dict(os.environ, {'TEST_BIN': '/usr/local'}):
            binary_path = get_binary_path("TEST_BIN", "test-binary")
            expected_path = Path("/usr/local/bin/test-binary")
            if os.name == 'nt':
                expected_path = Path("/usr/local/bin/test-binary.exe")
            assert binary_path == expected_path

    def test_get_binary_path_with_default(self):
        """Test getting binary path with default fallback."""
        with patch.dict(os.environ, {}, clear=True):
            default_path = Path("/default/bin")
            binary_path = get_binary_path("MISSING_VAR", "test-binary", default_path)
            expected_path = default_path / "bin" / "test-binary"
            if os.name == 'nt':
                expected_path = default_path / "bin" / "test-binary.exe"
            assert binary_path == expected_path

    def test_get_binary_path_no_env_no_default(self):
        """Test that get_binary_path raises KeyError when env var is missing and no default."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError, match="Environment variable MISSING_VAR is not set"):
                get_binary_path("MISSING_VAR", "test-binary")

    def test_is_windows(self):
        """Test Windows platform detection."""
        with patch('os.name', 'nt'):
            assert is_windows() is True
        with patch('os.name', 'posix'):
            assert is_windows() is False

    def test_is_unix_like(self):
        """Test Unix-like platform detection."""
        with patch('os.name', 'posix'):
            assert is_unix_like() is True
        with patch('os.name', 'nt'):
            assert is_unix_like() is False

    def test_get_platform_specific_path_windows_executable(self):
        """Test platform-specific path with Windows executable."""
        with patch('os.name', 'nt'):
            base_path = Path("/usr/local")
            path = get_platform_specific_path(base_path, "bin", "python")
            expected_path = base_path / "bin" / "python.exe"
            assert path == expected_path

    def test_get_platform_specific_path_unix_executable(self):
        """Test platform-specific path with Unix executable."""
        with patch('os.name', 'posix'):
            base_path = Path("/usr/local")
            path = get_platform_specific_path(base_path, "bin", "python")
            expected_path = base_path / "bin" / "python"
            assert path == expected_path

    def test_get_platform_specific_path_non_executable(self):
        """Test platform-specific path with non-executable file."""
        base_path = Path("/usr/local")
        path = get_platform_specific_path(base_path, "config", "settings.json")
        expected_path = base_path / "config" / "settings.json"
        assert path == expected_path


class TestPathUtilitiesIntegration:
    """Integration tests for path utilities."""

    def test_log_file_creation_integration(self):
        """Test that log file path points to a writable location."""
        timestamp = "test_20240101_120000"
        log_path = get_log_file_path(timestamp)
        
        # Ensure the parent directory exists and is writable
        assert log_path.parent.exists()
        assert log_path.parent.is_dir()
        
        # Test that we can write to the location
        try:
            log_path.write_text("test content")
            assert log_path.exists()
            assert log_path.read_text() == "test content"
        finally:
            # Clean up
            if log_path.exists():
                log_path.unlink()

    def test_temp_dir_integration(self):
        """Test that temp directory is actually usable."""
        temp_dir = get_temp_dir()
        
        # Test creating a file in the temp directory
        test_file = temp_dir / "test_file.txt"
        try:
            test_file.write_text("test content")
            assert test_file.exists()
            assert test_file.read_text() == "test content"
        finally:
            # Clean up
            if test_file.exists():
                test_file.unlink()

    def test_binary_path_integration(self):
        """Test binary path resolution with real environment."""
        # Test with a common environment variable
        try:
            # Try to get PATH environment variable
            path_binary = get_binary_path("PATH", "python", Path("/usr/bin"))
            assert isinstance(path_binary, Path)
        except KeyError:
            # If PATH is not set, test with a default
            path_binary = get_binary_path("PATH", "python", Path("/usr/bin"))
            assert isinstance(path_binary, Path)
            assert path_binary.parent == Path("/usr/bin/bin") 