"""Pytest configuration and fixtures for Bitswap tests."""

from unittest.mock import MagicMock

import pytest

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.client import BitswapClient


@pytest.fixture
def mock_host():
    """Create a mock libp2p host."""
    host = MagicMock()
    host.get_id.return_value = b"mock_peer_id"
    host.get_addrs.return_value = []
    host.set_stream_handler = MagicMock()
    return host


@pytest.fixture
def block_store():
    """Create a fresh MemoryBlockStore."""
    return MemoryBlockStore()


@pytest.fixture
def bitswap_client(mock_host, block_store):
    """Create a BitswapClient with mock host and fresh block store."""
    return BitswapClient(mock_host, block_store=block_store)


@pytest.fixture
def sample_data():
    """Provide sample test data."""
    return {
        "small": b"Hello, World!",
        "medium": b"x" * 1024,  # 1KB
        "large": b"y" * (256 * 1024),  # 256KB
    }
