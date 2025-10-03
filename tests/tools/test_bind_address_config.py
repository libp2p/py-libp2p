"""
Test for environment variable configuration of LIBP2P_BIND.

This test verifies that PR #892's fix for the DHT performance issue works correctly
by allowing configurable bind addresses via the LIBP2P_BIND environment variable.
"""

import importlib
import os

import pytest
import multiaddr


def test_default_bind_address_secure():
    """Test that default binding is secure (127.0.0.1)."""
    # Clear any existing environment variable
    if "LIBP2P_BIND" in os.environ:
        del os.environ["LIBP2P_BIND"]

    # Reload the constants module to get fresh configuration
    import libp2p.tools.constants

    importlib.reload(libp2p.tools.constants)

    # Verify default is secure
    assert libp2p.tools.constants.DEFAULT_BIND_ADDRESS == "127.0.0.1"
    assert str(libp2p.tools.constants.LISTEN_MADDR) == "/ip4/127.0.0.1/tcp/0"


def test_environment_variable_override():
    """Test that LIBP2P_BIND environment variable overrides default."""
    # Set environment variable
    os.environ["LIBP2P_BIND"] = "0.0.0.0"

    # Reload the constants module to pick up new environment
    import libp2p.tools.constants

    importlib.reload(libp2p.tools.constants)

    # Verify override works
    assert libp2p.tools.constants.DEFAULT_BIND_ADDRESS == "0.0.0.0"
    assert str(libp2p.tools.constants.LISTEN_MADDR) == "/ip4/0.0.0.0/tcp/0"

    # Clean up
    del os.environ["LIBP2P_BIND"]


def test_custom_ip_address_override():
    """Test that custom IP addresses work via environment variable."""
    custom_ip = "192.168.1.100"
    os.environ["LIBP2P_BIND"] = custom_ip

    # Reload the constants module
    import libp2p.tools.constants

    importlib.reload(libp2p.tools.constants)

    # Verify custom IP works
    assert libp2p.tools.constants.DEFAULT_BIND_ADDRESS == custom_ip
    assert str(libp2p.tools.constants.LISTEN_MADDR) == f"/ip4/{custom_ip}/tcp/0"

    # Clean up
    del os.environ["LIBP2P_BIND"]


def test_multiaddr_construction():
    """Test that the constructed multiaddr is valid."""
    os.environ["LIBP2P_BIND"] = "0.0.0.0"

    # Reload the constants module
    import libp2p.tools.constants

    importlib.reload(libp2p.tools.constants)

    # Verify multiaddr is properly constructed and valid
    maddr = libp2p.tools.constants.LISTEN_MADDR
    assert isinstance(maddr, multiaddr.Multiaddr)

    # Verify it has the expected components
    protocols = list(maddr.protocols())
    assert len(protocols) == 2
    assert protocols[0].name == "ip4"
    assert protocols[1].name == "tcp"

    # Verify the address value
    assert maddr.value_for_protocol("ip4") == "0.0.0.0"
    assert maddr.value_for_protocol("tcp") == "0"

    # Clean up
    del os.environ["LIBP2P_BIND"]


def test_invalid_ipv4_address_fallback():
    """Test that invalid IPv4 addresses fallback to 127.0.0.1."""
    invalid_addresses = [
        "17.0.0.",  # Incomplete IP address
        "256.1.1.1",  # Invalid octet
        "not.an.ip",  # Non-numeric
        "192.168.1",  # Missing octet
        "192.168.1.1.1",  # Too many octets
        "::1",  # IPv6 address
        "",  # Empty string
        "localhost",  # Hostname
    ]

    for invalid_addr in invalid_addresses:
        os.environ["LIBP2P_BIND"] = invalid_addr

        # Reload the constants module
        import libp2p.tools.constants

        importlib.reload(libp2p.tools.constants)

        # Verify fallback to secure default
        assert libp2p.tools.constants.DEFAULT_BIND_ADDRESS == "127.0.0.1"
        assert str(libp2p.tools.constants.LISTEN_MADDR) == "/ip4/127.0.0.1/tcp/0"

        # Clean up
        del os.environ["LIBP2P_BIND"]


def test_valid_ipv4_addresses():
    """Test that various valid IPv4 addresses work correctly."""
    valid_addresses = [
        "127.0.0.1",  # Localhost
        "0.0.0.0",  # All interfaces
        "192.168.1.1",  # Private network
        "10.0.0.1",  # Private network
        "172.16.0.1",  # Private network
        "8.8.8.8",  # Public DNS
        "255.255.255.255",  # Broadcast
    ]

    for valid_addr in valid_addresses:
        os.environ["LIBP2P_BIND"] = valid_addr

        # Reload the constants module
        import libp2p.tools.constants

        importlib.reload(libp2p.tools.constants)

        # Verify the address is used as-is
        assert libp2p.tools.constants.DEFAULT_BIND_ADDRESS == valid_addr
        assert str(libp2p.tools.constants.LISTEN_MADDR) == f"/ip4/{valid_addr}/tcp/0"

        # Clean up
        del os.environ["LIBP2P_BIND"]


@pytest.fixture(autouse=True)
def cleanup_environment():
    """Ensure clean environment after each test."""
    yield
    # Clean up after each test
    if "LIBP2P_BIND" in os.environ:
        del os.environ["LIBP2P_BIND"]

    # Reload with clean environment
    import libp2p.tools.constants

    importlib.reload(libp2p.tools.constants)
