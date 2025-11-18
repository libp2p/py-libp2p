"""
Test rcmgr module integration with core libp2p functionality.
"""

from libp2p.rcmgr import Direction, ResourceLimits, ResourceManager


def test_rcmgr_import():
    """Test that rcmgr module can be imported."""
    from libp2p.rcmgr import Direction, ResourceLimits, ResourceManager

    assert ResourceManager is not None
    assert Direction is not None
    assert ResourceLimits is not None


def test_rcmgr_basic_functionality():
    """Test basic rcmgr functionality."""
    limits = ResourceLimits(max_connections=10, max_memory_mb=1, max_streams=5)
    rm = ResourceManager(limits=limits)

    # Test basic operations
    assert rm.acquire_connection("peer1") is True
    assert rm.acquire_memory(512) is True
    assert rm.acquire_stream("peer1", Direction.INBOUND) is True

    # Test stats
    stats = rm.get_stats()
    assert "connections" in stats
    assert "memory_bytes" in stats
    assert "streams" in stats

    # Clean up
    rm.release_memory(512)
    rm.release_stream("peer1", Direction.INBOUND)
    rm.release_connection("peer1")


def test_rcmgr_direction_enum():
    """Test Direction enum functionality."""
    assert Direction.INBOUND == 0
    assert Direction.OUTBOUND == 1
    assert str(Direction.INBOUND) == "0"
    assert str(Direction.OUTBOUND) == "1"


def test_rcmgr_python_version_compatibility():
    """Test that rcmgr works with different Python versions."""
    import sys

    # Test that we're using modern Python features correctly
    assert sys.version_info >= (3, 10), f"Python {sys.version_info} is not >= 3.10"

    # Test that our type annotations work
    from typing import get_type_hints

    from libp2p.rcmgr.manager import ResourceManager

    # This should not raise an exception
    hints = get_type_hints(ResourceManager.__init__)
    assert hints is not None
