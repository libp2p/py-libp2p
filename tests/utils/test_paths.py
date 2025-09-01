"""
Tests for cross-platform path utilities.
"""

import os
from pathlib import Path
import tempfile

import pytest

from libp2p.utils.paths import (
    create_temp_file,
    ensure_dir_exists,
    find_executable,
    get_binary_path,
    get_config_dir,
    get_project_root,
    get_python_executable,
    get_script_binary_path,
    get_script_dir,
    get_temp_dir,
    get_venv_path,
    join_paths,
    normalize_path,
    resolve_relative_path,
)


class TestPathUtilities:
    """Test cross-platform path utilities."""

    def test_get_temp_dir(self):
        """Test that temp directory is accessible and exists."""
        temp_dir = get_temp_dir()
        assert isinstance(temp_dir, Path)
        assert temp_dir.exists()
        assert temp_dir.is_dir()
        # Should match system temp directory
        assert temp_dir == Path(tempfile.gettempdir())

    def test_get_project_root(self):
        """Test that project root is correctly determined."""
        project_root = get_project_root()
        assert isinstance(project_root, Path)
        assert project_root.exists()
        # Should contain pyproject.toml
        assert (project_root / "pyproject.toml").exists()
        # Should contain libp2p directory
        assert (project_root / "libp2p").exists()

    def test_join_paths(self):
        """Test cross-platform path joining."""
        # Test with strings
        result = join_paths("a", "b", "c")
        expected = Path("a") / "b" / "c"
        assert result == expected

        # Test with mixed types
        result = join_paths("a", Path("b"), "c")
        expected = Path("a") / "b" / "c"
        assert result == expected

        # Test with absolute path
        result = join_paths("/absolute", "path")
        expected = Path("/absolute") / "path"
        assert result == expected

    def test_ensure_dir_exists(self, tmp_path):
        """Test directory creation and existence checking."""
        # Test creating new directory
        new_dir = tmp_path / "new_dir"
        result = ensure_dir_exists(new_dir)
        assert result == new_dir
        assert new_dir.exists()
        assert new_dir.is_dir()

        # Test creating nested directory
        nested_dir = tmp_path / "parent" / "child" / "grandchild"
        result = ensure_dir_exists(nested_dir)
        assert result == nested_dir
        assert nested_dir.exists()
        assert nested_dir.is_dir()

        # Test with existing directory
        result = ensure_dir_exists(new_dir)
        assert result == new_dir
        assert new_dir.exists()

    def test_get_config_dir(self):
        """Test platform-specific config directory."""
        config_dir = get_config_dir()
        assert isinstance(config_dir, Path)

        if os.name == "nt":  # Windows
            # Should be in AppData/Roaming or user home
            assert "AppData" in str(config_dir) or "py-libp2p" in str(config_dir)
        else:  # Unix-like
            # Should be in ~/.config
            assert ".config" in str(config_dir)
            assert "py-libp2p" in str(config_dir)

    def test_get_script_dir(self):
        """Test script directory detection."""
        # Test with current file
        script_dir = get_script_dir(__file__)
        assert isinstance(script_dir, Path)
        assert script_dir.exists()
        assert script_dir.is_dir()
        # Should contain this test file
        assert (script_dir / "test_paths.py").exists()

    def test_create_temp_file(self):
        """Test temporary file creation."""
        temp_file = create_temp_file()
        assert isinstance(temp_file, Path)
        assert temp_file.parent == get_temp_dir()
        assert temp_file.name.startswith("py-libp2p_")
        assert temp_file.name.endswith(".log")

        # Test with custom prefix and suffix
        temp_file = create_temp_file(prefix="test_", suffix=".txt")
        assert temp_file.name.startswith("test_")
        assert temp_file.name.endswith(".txt")

    def test_resolve_relative_path(self, tmp_path):
        """Test relative path resolution."""
        base_path = tmp_path / "base"
        base_path.mkdir()

        # Test relative path
        relative_path = "subdir/file.txt"
        result = resolve_relative_path(base_path, relative_path)
        expected = (base_path / "subdir" / "file.txt").resolve()
        assert result == expected

        # Test absolute path (platform-agnostic)
        if os.name == "nt":  # Windows
            absolute_path = "C:\\absolute\\path"
        else:  # Unix-like
            absolute_path = "/absolute/path"
        result = resolve_relative_path(base_path, absolute_path)
        assert result == Path(absolute_path)

    def test_normalize_path(self, tmp_path):
        """Test path normalization."""
        # Test with relative path
        relative_path = tmp_path / ".." / "normalize_test"
        result = normalize_path(relative_path)
        assert result.is_absolute()
        assert "normalize_test" in str(result)

        # Test with absolute path
        absolute_path = tmp_path / "test_file"
        result = normalize_path(absolute_path)
        assert result.is_absolute()
        assert result == absolute_path.resolve()

    def test_get_venv_path(self, monkeypatch):
        """Test virtual environment path detection."""
        # Test when no virtual environment is active
        # Temporarily clear VIRTUAL_ENV to test the "no venv" case
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        result = get_venv_path()
        assert result is None

        # Test when virtual environment is active
        test_venv_path = "/path/to/venv"
        monkeypatch.setenv("VIRTUAL_ENV", test_venv_path)
        result = get_venv_path()
        assert result == Path(test_venv_path)

    def test_get_python_executable(self):
        """Test Python executable path detection."""
        result = get_python_executable()
        assert isinstance(result, Path)
        assert result.exists()
        assert result.name.startswith("python")

    def test_find_executable(self):
        """Test executable finding in PATH."""
        # Test with non-existent executable
        result = find_executable("nonexistent_executable")
        assert result is None

        # Test with existing executable (python should be available)
        result = find_executable("python")
        if result:
            assert isinstance(result, Path)
            assert result.exists()

    def test_get_script_binary_path(self):
        """Test script binary path detection."""
        result = get_script_binary_path()
        assert isinstance(result, Path)
        assert result.exists()
        assert result.is_dir()

    def test_get_binary_path(self, monkeypatch):
        """Test binary path resolution with virtual environment."""
        # Test when no virtual environment is active
        result = get_binary_path("python")
        if result:
            assert isinstance(result, Path)
            assert result.exists()

        # Test when virtual environment is active
        test_venv_path = "/path/to/venv"
        monkeypatch.setenv("VIRTUAL_ENV", test_venv_path)
        # This test is more complex as it depends on the actual venv structure
        # We'll just verify the function doesn't crash
        result = get_binary_path("python")
        # Result can be None if binary not found in venv
        if result:
            assert isinstance(result, Path)


class TestCrossPlatformCompatibility:
    """Test cross-platform compatibility."""

    def test_config_dir_platform_specific_windows(self, monkeypatch):
        """Test config directory respects Windows conventions."""
        import platform

        # Only run this test on Windows systems
        if platform.system() != "Windows":
            pytest.skip("This test only runs on Windows systems")

        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setenv("APPDATA", "C:\\Users\\Test\\AppData\\Roaming")
        config_dir = get_config_dir()
        assert "AppData" in str(config_dir)
        assert "py-libp2p" in str(config_dir)

    def test_path_separators_consistent(self):
        """Test that path separators are handled consistently."""
        # Test that join_paths uses platform-appropriate separators
        result = join_paths("dir1", "dir2", "file.txt")
        expected = Path("dir1") / "dir2" / "file.txt"
        assert result == expected

        # Test that the result uses correct separators for the platform
        if os.name == "nt":  # Windows
            assert "\\" in str(result) or "/" in str(result)
        else:  # Unix-like
            assert "/" in str(result)

    def test_temp_file_uniqueness(self):
        """Test that temporary files have unique names."""
        files = set()
        for _ in range(10):
            temp_file = create_temp_file()
            assert temp_file not in files
            files.add(temp_file)


class TestBackwardCompatibility:
    """Test backward compatibility with existing code patterns."""

    def test_path_operations_equivalent(self):
        """Test that new path operations are equivalent to old os.path operations."""
        # Test join_paths vs os.path.join
        parts = ["a", "b", "c"]
        new_result = join_paths(*parts)
        old_result = Path(os.path.join(*parts))
        assert new_result == old_result

        # Test get_script_dir vs os.path.dirname(os.path.abspath(__file__))
        new_script_dir = get_script_dir(__file__)
        old_script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        assert new_script_dir == old_script_dir

    def test_existing_functionality_preserved(self):
        """Ensure no existing functionality is broken."""
        # Test that all functions return Path objects
        assert isinstance(get_temp_dir(), Path)
        assert isinstance(get_project_root(), Path)
        assert isinstance(join_paths("a", "b"), Path)
        assert isinstance(ensure_dir_exists(tempfile.gettempdir()), Path)
        assert isinstance(get_config_dir(), Path)
        assert isinstance(get_script_dir(__file__), Path)
        assert isinstance(create_temp_file(), Path)
        assert isinstance(resolve_relative_path(".", "test"), Path)
        assert isinstance(normalize_path("."), Path)
        assert isinstance(get_python_executable(), Path)
        assert isinstance(get_script_binary_path(), Path)

        # Test optional return types
        venv_path = get_venv_path()
        if venv_path is not None:
            assert isinstance(venv_path, Path)
