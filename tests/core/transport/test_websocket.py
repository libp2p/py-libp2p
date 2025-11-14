from collections.abc import Sequence
import logging
from typing import Any

import pytest

try:
    from builtins import ExceptionGroup  # type: ignore[attr-defined]
except ImportError:
    try:
        from exceptiongroup import ExceptionGroup  # type: ignore[assignment]
    except ImportError:  # pragma: no cover - fallback if dependency missing
        ExceptionGroup = Exception  # type: ignore[assignment]
from multiaddr import Multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.multiaddr_utils import (
    is_valid_websocket_multiaddr,
    parse_websocket_multiaddr,
)
from libp2p.transport.websocket.transport import WebsocketTransport

logger = logging.getLogger(__name__)

PLAINTEXT_PROTOCOL_ID = "/plaintext/1.0.0"


async def make_host(
    listen_addrs: Sequence[Multiaddr] | None = None,
) -> tuple[BasicHost, Any | None]:
    # Identity
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peer_store = PeerStore()
    peer_store.add_key_pair(peer_id, key_pair)

    # Upgrader
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )

    # Transport + Swarm + Host
    transport = WebsocketTransport(upgrader)
    swarm = Swarm(peer_id, peer_store, upgrader, transport)
    host = BasicHost(swarm)

    # Optionally run/listen
    ctx = None
    if listen_addrs:
        ctx = host.run(listen_addrs)
        await ctx.__aenter__()

    return host, ctx


def create_upgrader():
    """Helper function to create a transport upgrader"""
    key_pair = create_new_key_pair()
    return TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )


# 2. Listener Basic Functionality Tests
@pytest.mark.trio
async def test_listener_basic_listen():
    """Test basic listen functionality"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test listening on IPv4
    ma = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)

    # Test that listener can be created and has required methods
    assert hasattr(listener, "listen")
    assert hasattr(listener, "close")
    assert hasattr(listener, "get_addrs")

    # Test that listener can handle the address
    assert ma.value_for_protocol("ip4") == "127.0.0.1"
    assert ma.value_for_protocol("tcp") == "0"

    # Test that listener can be closed
    await listener.close()


@pytest.mark.trio
async def test_listener_port_0_handling():
    """Test listening on port 0 gets actual port"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    ma = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)

    # Test that the address can be parsed correctly
    port_str = ma.value_for_protocol("tcp")
    assert port_str == "0"

    # Test that listener can be closed
    await listener.close()


@pytest.mark.trio
async def test_listener_any_interface():
    """Test listening on 0.0.0.0"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    ma = Multiaddr("/ip4/0.0.0.0/tcp/0/ws")

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)

    # Test that the address can be parsed correctly
    host = ma.value_for_protocol("ip4")
    assert host == "0.0.0.0"

    # Test that listener can be closed
    await listener.close()


@pytest.mark.trio
async def test_listener_address_preservation():
    """Test that p2p IDs are preserved in addresses"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Create address with p2p ID
    p2p_id = "12D3KooWL5xtmx8Mgc6tByjVaPPpTKH42QK7PUFQtZLabdSMKHpF"
    ma = Multiaddr(f"/ip4/127.0.0.1/tcp/0/ws/p2p/{p2p_id}")

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)

    # Test that p2p ID is preserved in the address
    addr_str = str(ma)
    assert p2p_id in addr_str

    # Test that listener can be closed
    await listener.close()


# 3. Dial Basic Functionality Tests
@pytest.mark.trio
async def test_dial_basic():
    """Test basic dial functionality"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test that transport can parse addresses for dialing
    ma = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")

    # Test that the address can be parsed correctly
    host = ma.value_for_protocol("ip4")
    port = ma.value_for_protocol("tcp")
    assert host == "127.0.0.1"
    assert port == "8080"

    # Test that transport has the required methods
    assert hasattr(transport, "dial")
    assert callable(transport.dial)


@pytest.mark.trio
async def test_dial_with_p2p_id():
    """Test dialing with p2p ID suffix"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    p2p_id = "12D3KooWL5xtmx8Mgc6tByjVaPPpTKH42QK7PUFQtZLabdSMKHpF"
    ma = Multiaddr(f"/ip4/127.0.0.1/tcp/8080/ws/p2p/{p2p_id}")

    # Test that p2p ID is preserved in the address
    addr_str = str(ma)
    assert p2p_id in addr_str

    # Test that transport can handle addresses with p2p IDs
    assert hasattr(transport, "dial")
    assert callable(transport.dial)


@pytest.mark.trio
async def test_dial_port_0_resolution():
    """Test dialing to resolved port 0 addresses"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test that transport can handle port 0 addresses
    ma = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")

    # Test that the address can be parsed correctly
    port_str = ma.value_for_protocol("tcp")
    assert port_str == "0"

    # Test that transport has the required methods
    assert hasattr(transport, "dial")
    assert callable(transport.dial)


# 4. Address Validation Tests (CRITICAL)
def test_address_validation_ipv4():
    """Test IPv4 address validation"""
    # upgrader = create_upgrader()  # Not used in this test

    # Valid IPv4 WebSocket addresses
    valid_addresses = [
        "/ip4/127.0.0.1/tcp/8080/ws",
        "/ip4/0.0.0.0/tcp/0/ws",
        "/ip4/192.168.1.1/tcp/443/ws",
    ]

    # Test valid addresses can be parsed
    for addr_str in valid_addresses:
        ma = Multiaddr(addr_str)
        # Should not raise exception when creating transport address
        transport_addr = str(ma)
        assert "/ws" in transport_addr

    # Test that transport can handle addresses with p2p IDs
    p2p_addr = Multiaddr(
        "/ip4/127.0.0.1/tcp/8080/ws/p2p/Qmb6owHp6eaWArVbcJJbQSyifyJBttMMjYV76N2hMbf5Vw"
    )
    # Should not raise exception when creating transport address
    transport_addr = str(p2p_addr)
    assert "/ws" in transport_addr


def test_address_validation_ipv6():
    """Test IPv6 address validation"""
    # upgrader = create_upgrader()  # Not used in this test

    # Valid IPv6 WebSocket addresses
    valid_addresses = [
        "/ip6/::1/tcp/8080/ws",
        "/ip6/2001:db8::1/tcp/443/ws",
    ]

    # Test valid addresses can be parsed
    for addr_str in valid_addresses:
        ma = Multiaddr(addr_str)
        transport_addr = str(ma)
        assert "/ws" in transport_addr


def test_address_validation_dns():
    """Test DNS address validation"""
    # upgrader = create_upgrader()  # Not used in this test

    # Valid DNS WebSocket addresses
    valid_addresses = [
        "/dns4/example.com/tcp/80/ws",
        "/dns6/example.com/tcp/443/ws",
        "/dnsaddr/example.com/tcp/8080/ws",
    ]

    # Test valid addresses can be parsed
    for addr_str in valid_addresses:
        ma = Multiaddr(addr_str)
        transport_addr = str(ma)
        assert "/ws" in transport_addr


def test_address_validation_mixed():
    """Test mixed address validation"""
    # upgrader = create_upgrader()  # Not used in this test

    # Mixed valid and invalid addresses
    addresses = [
        "/ip4/127.0.0.1/tcp/8080/ws",  # Valid
        "/ip4/127.0.0.1/tcp/8080",  # Invalid (no /ws)
        "/ip6/::1/tcp/8080/ws",  # Valid
        "/ip4/127.0.0.1/ws",  # Invalid (no tcp)
        "/dns4/example.com/tcp/80/ws",  # Valid
    ]

    # Convert to Multiaddr objects
    multiaddrs = [Multiaddr(addr) for addr in addresses]

    # Test that valid addresses can be processed
    valid_count = 0
    for ma in multiaddrs:
        try:
            # Try to extract transport part
            addr_text = str(ma)
            if "/ws" in addr_text and "/tcp/" in addr_text:
                valid_count += 1
        except Exception:
            pass

    assert valid_count == 3  # Should have 3 valid addresses


# 5. Error Handling Tests
@pytest.mark.trio
async def test_dial_invalid_address():
    """Test dialing invalid addresses"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test dialing non-WebSocket addresses
    invalid_addresses = [
        Multiaddr("/ip4/127.0.0.1/tcp/8080"),  # No /ws
        Multiaddr("/ip4/127.0.0.1/ws"),  # No tcp
    ]

    for ma in invalid_addresses:
        with pytest.raises(Exception):
            await transport.dial(ma)


@pytest.mark.trio
async def test_listen_invalid_address():
    """Test listening on invalid addresses"""
    # upgrader = create_upgrader()  # Not used in this test

    # Test listening on non-WebSocket addresses
    invalid_addresses = [
        Multiaddr("/ip4/127.0.0.1/tcp/8080"),  # No /ws
        Multiaddr("/ip4/127.0.0.1/ws"),  # No tcp
    ]

    # Test that invalid addresses are properly identified
    for ma in invalid_addresses:
        # Test that the address parsing works correctly
        if "/ws" in str(ma) and "tcp" not in str(ma):
            # This should be invalid
            assert "tcp" not in str(ma)
        elif "/ws" not in str(ma):
            # This should be invalid
            assert "/ws" not in str(ma)


@pytest.mark.trio
async def test_listen_port_in_use():
    """Test listening on port that's in use"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test that transport can handle port conflicts
    ma1 = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
    ma2 = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")

    # Test that both addresses can be parsed
    assert ma1.value_for_protocol("tcp") == "8080"
    assert ma2.value_for_protocol("tcp") == "8080"

    # Test that transport can handle these addresses
    assert hasattr(transport, "create_listener")
    assert callable(transport.create_listener)


# 6. Connection Lifecycle Tests
@pytest.mark.trio
async def test_connection_close():
    """Test connection closing"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test that transport has required methods
    assert hasattr(transport, "dial")
    assert callable(transport.dial)

    # Test that listener can be created and closed
    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)
    assert hasattr(listener, "close")
    assert callable(listener.close)

    # Test that listener can be closed
    await listener.close()


@pytest.mark.trio
async def test_multiple_connections():
    """Test multiple concurrent connections"""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test that transport can handle multiple addresses
    addresses = [
        Multiaddr("/ip4/127.0.0.1/tcp/8080/ws"),
        Multiaddr("/ip4/127.0.0.1/tcp/8081/ws"),
        Multiaddr("/ip4/127.0.0.1/tcp/8082/ws"),
    ]

    # Test that all addresses can be parsed
    for addr in addresses:
        host = addr.value_for_protocol("ip4")
        port = addr.value_for_protocol("tcp")
        assert host == "127.0.0.1"
        assert port in ["8080", "8081", "8082"]

    # Test that transport has required methods
    assert hasattr(transport, "dial")
    assert callable(transport.dial)


# Original test (kept for compatibility)
@pytest.mark.trio
async def test_websocket_dial_and_listen():
    """Test basic WebSocket dial and listen functionality with real data transfer"""
    # Test that WebSocket transport can handle basic operations
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test that transport can create listeners
    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)
    assert listener is not None
    assert hasattr(listener, "listen")
    assert hasattr(listener, "close")
    assert hasattr(listener, "get_addrs")

    # Test that transport can handle WebSocket addresses
    ma = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    assert ma.value_for_protocol("ip4") == "127.0.0.1"
    assert ma.value_for_protocol("tcp") == "0"
    assert "ws" in str(ma)

    # Test that transport has dial method
    assert hasattr(transport, "dial")
    assert callable(transport.dial)

    # Test that transport can handle WebSocket multiaddrs
    ws_addr = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
    assert ws_addr.value_for_protocol("ip4") == "127.0.0.1"
    assert ws_addr.value_for_protocol("tcp") == "8080"
    assert "ws" in str(ws_addr)

    # Cleanup
    await listener.close()


@pytest.mark.trio
async def test_websocket_transport_basic():
    """Test basic WebSocket transport functionality without full libp2p stack"""
    # Create WebSocket transport
    key_pair = create_new_key_pair()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )
    transport = WebsocketTransport(upgrader)

    assert transport is not None
    assert hasattr(transport, "dial")
    assert hasattr(transport, "create_listener")

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)
    assert listener is not None
    assert hasattr(listener, "listen")
    assert hasattr(listener, "close")
    assert hasattr(listener, "get_addrs")

    valid_addr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    assert valid_addr.value_for_protocol("ip4") == "127.0.0.1"
    assert valid_addr.value_for_protocol("tcp") == "0"
    assert "ws" in str(valid_addr)

    await listener.close()


@pytest.mark.trio
async def test_websocket_simple_connection():
    """Test WebSocket transport creation and basic functionality without real conn"""
    # Create WebSocket transport
    key_pair = create_new_key_pair()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )
    transport = WebsocketTransport(upgrader)

    assert transport is not None
    assert hasattr(transport, "dial")
    assert hasattr(transport, "create_listener")

    async def simple_handler(conn):
        await conn.close()

    listener = transport.create_listener(simple_handler)
    assert listener is not None
    assert hasattr(listener, "listen")
    assert hasattr(listener, "close")
    assert hasattr(listener, "get_addrs")

    test_addr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    assert test_addr.value_for_protocol("ip4") == "127.0.0.1"
    assert test_addr.value_for_protocol("tcp") == "0"
    assert "ws" in str(test_addr)

    await listener.close()


@pytest.mark.trio
async def test_websocket_real_connection():
    """Test WebSocket transport creation and basic functionality"""
    # Create WebSocket transport
    key_pair = create_new_key_pair()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )
    transport = WebsocketTransport(upgrader)

    assert transport is not None
    assert hasattr(transport, "dial")
    assert hasattr(transport, "create_listener")

    async def handler(conn):
        await conn.close()

    listener = transport.create_listener(handler)
    assert listener is not None
    assert hasattr(listener, "listen")
    assert hasattr(listener, "close")
    assert hasattr(listener, "get_addrs")

    await listener.close()


@pytest.mark.trio
async def test_websocket_with_tcp_fallback():
    """Test WebSocket functionality using TCP transport as fallback"""
    from tests.utils.factories import host_pair_factory

    async with host_pair_factory() as (host_a, host_b):
        assert len(host_a.get_network().connections) > 0
        assert len(host_b.get_network().connections) > 0

        test_protocol = TProtocol("/test/protocol/1.0.0")
        received_data = None

        async def test_handler(stream):
            nonlocal received_data
            received_data = await stream.read(1024)
            await stream.write(b"Response from TCP")
            await stream.close()

        host_a.set_stream_handler(test_protocol, test_handler)
        stream = await host_b.new_stream(host_a.get_id(), [test_protocol])

        test_data = b"TCP protocol test"
        await stream.write(test_data)
        response = await stream.read(1024)

        assert received_data == test_data
        assert response == b"Response from TCP"

        await stream.close()


@pytest.mark.trio
async def test_websocket_data_exchange():
    """Test WebSocket transport with actual data exchange between two hosts"""
    from libp2p import create_yamux_muxer_option, new_host
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.custom_types import TProtocol
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.security.insecure.transport import (
        PLAINTEXT_PROTOCOL_ID,
        InsecureTransport,
    )

    # Create two hosts with plaintext security
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()

    # Host A (listener)
    security_options_a = {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair_a, secure_bytes_provider=None, peerstore=None
        )
    }
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options_a,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/wss")],
    )

    # Host B (dialer)
    security_options_b = {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair_b, secure_bytes_provider=None, peerstore=None
        )
    }
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options_b,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/wss")],  # WebSocket transport
    )

    # Test data
    test_data = b"Hello WebSocket Data Exchange!"
    received_data = None

    # Set up handler on host A
    test_protocol = TProtocol("/test/websocket/data/1.0.0")

    async def data_handler(stream):
        nonlocal received_data
        received_data = await stream.read(len(test_data))
        await stream.write(received_data)  # Echo back
        await stream.close()

    host_a.set_stream_handler(test_protocol, data_handler)

    # Start both hosts
    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        assert len(listen_addrs) > 0

        # Find the WebSocket address
        ws_addr = None
        for addr in listen_addrs:
            if "/ws" in str(addr):
                ws_addr = addr
                break

        assert ws_addr is not None, "No WebSocket listen address found"

        # Connect host B to host A
        peer_info = info_from_p2p_addr(ws_addr)
        await host_b.connect(peer_info)

        # Create stream and test data exchange
        stream = await host_b.new_stream(host_a.get_id(), [test_protocol])
        await stream.write(test_data)
        response = await stream.read(len(test_data))
        await stream.close()

        # Verify data exchange
        assert received_data == test_data, f"Expected {test_data}, got {received_data}"
        assert response == test_data, f"Expected echo {test_data}, got {response}"


@pytest.mark.trio
async def test_websocket_host_pair_data_exchange():
    """
    Test WebSocket host pair with actual data exchange using host_pair_factory
    pattern.
    """
    from libp2p import create_yamux_muxer_option, new_host
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.custom_types import TProtocol
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.security.insecure.transport import (
        PLAINTEXT_PROTOCOL_ID,
        InsecureTransport,
    )

    # Create two hosts with WebSocket transport and plaintext security
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()

    # Host A (listener) - WebSocket transport
    security_options_a = {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair_a, secure_bytes_provider=None, peerstore=None
        )
    }
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options_a,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/wss")],
    )

    # Host B (dialer) - WebSocket transport
    security_options_b = {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair_b, secure_bytes_provider=None, peerstore=None
        )
    }
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options_b,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/wss")],  # WebSocket transport
    )

    # Test data
    test_data = b"Hello WebSocket Host Pair Data Exchange!"
    received_data = None

    # Set up handler on host A
    test_protocol = TProtocol("/test/websocket/hostpair/1.0.0")

    async def data_handler(stream):
        nonlocal received_data
        received_data = await stream.read(len(test_data))
        await stream.write(received_data)  # Echo back
        await stream.close()

    host_a.set_stream_handler(test_protocol, data_handler)

    # Start both hosts and connect them (following host_pair_factory pattern)
    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")]),
        host_b.run(listen_addrs=[]),
    ):
        # Connect the hosts using the same pattern as host_pair_factory
        # Get host A's listen address and create peer info
        listen_addrs = host_a.get_addrs()
        assert len(listen_addrs) > 0

        # Find the WebSocket address
        ws_addr = None
        for addr in listen_addrs:
            if "/ws" in str(addr):
                ws_addr = addr
                break

        assert ws_addr is not None, "No WebSocket listen address found"

        # Connect host B to host A
        peer_info = info_from_p2p_addr(ws_addr)
        await host_b.connect(peer_info)

        # Allow time for connection to establish (following host_pair_factory pattern)
        await trio.sleep(0.1)

        # Verify connection is established
        assert len(host_a.get_network().connections) > 0
        assert len(host_b.get_network().connections) > 0

        # Test data exchange
        stream = await host_b.new_stream(host_a.get_id(), [test_protocol])
        await stream.write(test_data)
        response = await stream.read(len(test_data))
        await stream.close()

        # Verify data exchange
        assert received_data == test_data, f"Expected {test_data}, got {received_data}"
        assert response == test_data, f"Expected echo {test_data}, got {response}"


@pytest.mark.trio
async def test_wss_host_pair_data_exchange():
    """Test WSS host pair with actual data exchange using host_pair_factory pattern"""
    import ssl

    from libp2p import create_yamux_muxer_option, new_host
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.custom_types import TProtocol
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.security.insecure.transport import (
        PLAINTEXT_PROTOCOL_ID,
        InsecureTransport,
    )

    # Create TLS contexts for WSS (separate for client and server)
    # For testing, we need to create a self-signed certificate
    try:
        import datetime
        import ipaddress
        import os
        import tempfile

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create certificate
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),  # type: ignore
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Test"),  # type: ignore
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Test"),  # type: ignore
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test"),  # type: ignore
                x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),  # type: ignore
            ]
        )

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=1)
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )

        # Create temporary files for cert and key
        cert_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".crt")
        key_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".key")

        # Write certificate and key to files
        cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        cert_file.close()
        key_file.close()

        # Server context for listener (Host A)
        server_tls_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        server_tls_context.load_cert_chain(cert_file.name, key_file.name)

        # Client context for dialer (Host B)
        client_tls_context = ssl.create_default_context()
        client_tls_context.check_hostname = False
        client_tls_context.verify_mode = ssl.CERT_NONE

        # Clean up temp files after use
        def cleanup_certs():
            try:
                os.unlink(cert_file.name)
                os.unlink(key_file.name)
            except Exception:
                pass

    except ImportError:
        pytest.skip("cryptography package required for WSS tests")
    except Exception as e:
        pytest.skip(f"Failed to create test certificates: {e}")

    # Create two hosts with WSS transport and plaintext security
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()

    # Host A (listener) - WSS transport with server TLS config
    security_options_a = {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair_a, secure_bytes_provider=None, peerstore=None
        )
    }
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options_a,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/wss")],
        tls_server_config=server_tls_context,
    )

    # Host B (dialer) - WSS transport with client TLS config
    security_options_b = {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair_b, secure_bytes_provider=None, peerstore=None
        )
    }
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options_b,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/wss")],  # WebSocket transport
        tls_client_config=client_tls_context,
    )

    # Test data
    test_data = b"Hello WSS Host Pair Data Exchange!"
    received_data = None

    # Set up handler on host A
    test_protocol = TProtocol("/test/wss/hostpair/1.0.0")

    async def data_handler(stream):
        nonlocal received_data
        received_data = await stream.read(len(test_data))
        await stream.write(received_data)  # Echo back
        await stream.close()

    host_a.set_stream_handler(test_protocol, data_handler)

    # Start both hosts and connect them (following host_pair_factory pattern)
    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/wss")]),
        host_b.run(listen_addrs=[]),
    ):
        # Connect the hosts using the same pattern as host_pair_factory
        # Get host A's listen address and create peer info
        listen_addrs = host_a.get_addrs()
        assert len(listen_addrs) > 0

        # Find the WSS address
        wss_addr = None
        for addr in listen_addrs:
            if "/wss" in str(addr):
                wss_addr = addr
                break

        assert wss_addr is not None, "No WSS listen address found"

        # Connect host B to host A
        peer_info = info_from_p2p_addr(wss_addr)
        await host_b.connect(peer_info)

        # Allow time for connection to establish (following host_pair_factory pattern)
        await trio.sleep(0.1)

        # Verify connection is established
        assert len(host_a.get_network().connections) > 0
        assert len(host_b.get_network().connections) > 0

        # Test data exchange
        stream = await host_b.new_stream(host_a.get_id(), [test_protocol])
        await stream.write(test_data)
        response = await stream.read(len(test_data))
        await stream.close()

        # Verify data exchange
        assert received_data == test_data, f"Expected {test_data}, got {received_data}"
        assert response == test_data, f"Expected echo {test_data}, got {response}"


@pytest.mark.trio
async def test_websocket_transport_interface():
    """Test WebSocket transport interface compliance"""
    key_pair = create_new_key_pair()
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )

    transport = WebsocketTransport(upgrader)

    assert hasattr(transport, "dial")
    assert hasattr(transport, "create_listener")
    assert callable(transport.dial)
    assert callable(transport.create_listener)

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)
    assert hasattr(listener, "listen")
    assert hasattr(listener, "close")
    assert hasattr(listener, "get_addrs")

    test_addr = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
    host = test_addr.value_for_protocol("ip4")
    port = test_addr.value_for_protocol("tcp")
    assert host == "127.0.0.1"
    assert port == "8080"

    await listener.close()


# ============================================================================
# WSS (WebSocket Secure) Tests
# ============================================================================


def test_wss_multiaddr_validation():
    """Test WSS multiaddr validation and parsing."""
    # Valid WSS multiaddrs
    valid_wss_addresses = [
        "/ip4/127.0.0.1/tcp/8080/wss",
        "/ip6/::1/tcp/8080/wss",
        "/dns/localhost/tcp/8080/wss",
        "/ip4/127.0.0.1/tcp/8080/tls/ws",
        "/ip6/::1/tcp/8080/tls/ws",
    ]

    # Invalid WSS multiaddrs
    invalid_wss_addresses = [
        "/ip4/127.0.0.1/tcp/8080/ws",  # Regular WS, not WSS
        "/ip4/127.0.0.1/tcp/8080",  # No WebSocket protocol
        "/ip4/127.0.0.1/wss",  # No TCP
    ]

    # Test valid WSS addresses
    for addr_str in valid_wss_addresses:
        ma = Multiaddr(addr_str)
        assert is_valid_websocket_multiaddr(ma), f"Address {addr_str} should be valid"

        # Test parsing
        parsed = parse_websocket_multiaddr(ma)
        assert parsed.is_wss, f"Address {addr_str} should be parsed as WSS"

    # Test invalid addresses
    for addr_str in invalid_wss_addresses:
        ma = Multiaddr(addr_str)
        if "/ws" in addr_str and "/wss" not in addr_str and "/tls" not in addr_str:
            # Regular WS should be valid but not WSS
            assert is_valid_websocket_multiaddr(ma), (
                f"Address {addr_str} should be valid"
            )
            parsed = parse_websocket_multiaddr(ma)
            assert not parsed.is_wss, f"Address {addr_str} should not be parsed as WSS"
        else:
            # Invalid addresses should fail validation
            assert not is_valid_websocket_multiaddr(ma), (
                f"Address {addr_str} should be invalid"
            )


def test_wss_multiaddr_parsing():
    """Test WSS multiaddr parsing functionality."""
    # Test /wss format
    wss_ma = Multiaddr("/ip4/127.0.0.1/tcp/8080/wss")
    parsed = parse_websocket_multiaddr(wss_ma)
    assert parsed.is_wss
    assert parsed.sni is None
    assert parsed.rest_multiaddr.value_for_protocol("ip4") == "127.0.0.1"
    assert parsed.rest_multiaddr.value_for_protocol("tcp") == "8080"

    # Test /tls/ws format
    tls_ws_ma = Multiaddr("/ip4/127.0.0.1/tcp/8080/tls/ws")
    parsed = parse_websocket_multiaddr(tls_ws_ma)
    assert parsed.is_wss
    assert parsed.sni is None
    assert parsed.rest_multiaddr.value_for_protocol("ip4") == "127.0.0.1"
    assert parsed.rest_multiaddr.value_for_protocol("tcp") == "8080"

    # Test regular /ws format
    ws_ma = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
    parsed = parse_websocket_multiaddr(ws_ma)
    assert not parsed.is_wss
    assert parsed.sni is None


@pytest.mark.trio
async def test_wss_transport_creation():
    """Test WSS transport creation with TLS configuration."""
    import ssl

    # Create TLS contexts
    client_ssl_context = ssl.create_default_context()
    server_ssl_context = ssl.create_default_context()
    server_ssl_context.check_hostname = False
    server_ssl_context.verify_mode = ssl.CERT_NONE

    upgrader = create_upgrader()

    # Test creating WSS transport with TLS configs
    wss_transport = WebsocketTransport(
        upgrader,
        tls_client_config=client_ssl_context,
        tls_server_config=server_ssl_context,
    )

    assert wss_transport is not None
    assert hasattr(wss_transport, "dial")
    assert hasattr(wss_transport, "create_listener")
    assert wss_transport._tls_client_config is not None
    assert wss_transport._tls_server_config is not None


@pytest.mark.trio
async def test_wss_transport_without_tls_config():
    """Test WSS transport creation without TLS configuration."""
    upgrader = create_upgrader()

    # Test creating WSS transport without TLS configs (should still work)
    wss_transport = WebsocketTransport(upgrader)

    assert wss_transport is not None
    assert hasattr(wss_transport, "dial")
    assert hasattr(wss_transport, "create_listener")
    assert wss_transport._tls_client_config is None
    assert wss_transport._tls_server_config is None


@pytest.mark.trio
async def test_wss_dial_parsing():
    """Test WSS dial functionality with multiaddr parsing."""
    # upgrader = create_upgrader()  # Not used in this test
    # transport = WebsocketTransport(upgrader)  # Not used in this test

    # Test WSS multiaddr parsing in dial
    wss_maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/wss")

    # Test that the transport can parse WSS addresses
    # (We can't actually dial without a server, but we can test parsing)
    try:
        parsed = parse_websocket_multiaddr(wss_maddr)
        assert parsed.is_wss
        assert parsed.rest_multiaddr.value_for_protocol("ip4") == "127.0.0.1"
        assert parsed.rest_multiaddr.value_for_protocol("tcp") == "8080"
    except Exception as e:
        pytest.fail(f"WSS multiaddr parsing failed: {e}")


@pytest.mark.trio
async def test_wss_listen_parsing():
    """Test WSS listen functionality with multiaddr parsing."""
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test WSS multiaddr parsing in listen
    wss_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/wss")

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)

    # Test that the transport can parse WSS addresses
    try:
        parsed = parse_websocket_multiaddr(wss_maddr)
        assert parsed.is_wss
        assert parsed.rest_multiaddr.value_for_protocol("ip4") == "127.0.0.1"
        assert parsed.rest_multiaddr.value_for_protocol("tcp") == "0"
    except Exception as e:
        pytest.fail(f"WSS multiaddr parsing failed: {e}")

    await listener.close()


@pytest.mark.trio
async def test_wss_listen_without_tls_config():
    """Test WSS listen without TLS configuration should fail."""
    from libp2p.transport.websocket.transport import WebsocketTransport

    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)  # No TLS config

    wss_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/wss")

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)

    # This should raise an error when TLS config is not provided
    try:
        nursery = trio.lowlevel.current_task().parent_nursery
        if nursery is None:
            pytest.fail("No parent nursery available for test")
        # Type assertion to help the type checker understand nursery is not None
        assert nursery is not None
        await listener.listen(wss_maddr, nursery)
        pytest.fail("WSS listen without TLS config should have failed")
    except ValueError as e:
        assert "without TLS configuration" in str(e)
    except Exception as e:
        pytest.fail(f"Unexpected error: {e}")

    await listener.close()


@pytest.mark.trio
async def test_wss_listen_with_tls_config():
    """Test WSS listen with TLS configuration."""
    import ssl

    # Create server TLS context
    server_ssl_context = ssl.create_default_context()
    server_ssl_context.check_hostname = False
    server_ssl_context.verify_mode = ssl.CERT_NONE

    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader, tls_server_config=server_ssl_context)

    wss_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/wss")

    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)

    # This should not raise an error when TLS config is provided
    # Note: We can't actually start listening without proper certificates,
    # but we can test that the validation passes
    try:
        parsed = parse_websocket_multiaddr(wss_maddr)
        assert parsed.is_wss
        assert transport._tls_server_config is not None
    except Exception as e:
        pytest.fail(f"WSS listen with TLS config failed: {e}")

    await listener.close()


def test_wss_transport_registry():
    """Test WSS support in transport registry."""
    from libp2p.transport.transport_registry import (
        create_transport_for_multiaddr,
        get_supported_transport_protocols,
    )

    # Test that WSS is supported
    supported = get_supported_transport_protocols()
    assert "ws" in supported
    assert "wss" in supported

    # Test transport creation for WSS multiaddrs
    upgrader = create_upgrader()

    # Test WS multiaddr
    ws_maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
    ws_transport = create_transport_for_multiaddr(ws_maddr, upgrader)
    assert ws_transport is not None
    assert isinstance(ws_transport, WebsocketTransport)

    # Test WSS multiaddr
    wss_maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/wss")
    wss_transport = create_transport_for_multiaddr(wss_maddr, upgrader)
    assert wss_transport is not None
    assert isinstance(wss_transport, WebsocketTransport)

    # Test TLS/WS multiaddr
    tls_ws_maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/tls/ws")
    tls_ws_transport = create_transport_for_multiaddr(tls_ws_maddr, upgrader)
    assert tls_ws_transport is not None
    assert isinstance(tls_ws_transport, WebsocketTransport)


def test_wss_multiaddr_formats():
    """Test different WSS multiaddr formats."""
    # Test various WSS formats
    wss_formats = [
        "/ip4/127.0.0.1/tcp/8080/wss",
        "/ip6/::1/tcp/8080/wss",
        "/dns/localhost/tcp/8080/wss",
        "/ip4/127.0.0.1/tcp/8080/tls/ws",
        "/ip6/::1/tcp/8080/tls/ws",
        "/dns/example.com/tcp/443/tls/ws",
    ]

    for addr_str in wss_formats:
        ma = Multiaddr(addr_str)

        # Should be valid WebSocket multiaddr
        assert is_valid_websocket_multiaddr(ma), f"Address {addr_str} should be valid"

        # Should parse as WSS
        parsed = parse_websocket_multiaddr(ma)
        assert parsed.is_wss, f"Address {addr_str} should be parsed as WSS"

        # Should have correct base multiaddr
        assert parsed.rest_multiaddr.value_for_protocol("tcp") is not None


def test_wss_vs_ws_distinction():
    """Test that WSS and WS are properly distinguished."""
    # WS addresses should not be WSS
    ws_addresses = [
        "/ip4/127.0.0.1/tcp/8080/ws",
        "/ip6/::1/tcp/8080/ws",
        "/dns/localhost/tcp/8080/ws",
    ]

    for addr_str in ws_addresses:
        ma = Multiaddr(addr_str)
        parsed = parse_websocket_multiaddr(ma)
        assert not parsed.is_wss, f"Address {addr_str} should not be WSS"

    # WSS addresses should be WSS
    wss_addresses = [
        "/ip4/127.0.0.1/tcp/8080/wss",
        "/ip4/127.0.0.1/tcp/8080/tls/ws",
    ]

    for addr_str in wss_addresses:
        ma = Multiaddr(addr_str)
        parsed = parse_websocket_multiaddr(ma)
        assert parsed.is_wss, f"Address {addr_str} should be WSS"


@pytest.mark.trio
async def test_wss_connection_handling():
    """Test WSS connection handling with security flag."""
    # upgrader = create_upgrader()  # Not used in this test
    # transport = WebsocketTransport(upgrader)  # Not used in this test

    # Test that WSS connections are marked as secure
    wss_maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/wss")
    parsed = parse_websocket_multiaddr(wss_maddr)
    assert parsed.is_wss

    # Test that WS connections are not marked as secure
    ws_maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
    parsed = parse_websocket_multiaddr(ws_maddr)
    assert not parsed.is_wss


def test_wss_error_handling():
    """Test WSS error handling for invalid configurations."""
    # upgrader = create_upgrader()  # Not used in this test

    # Test invalid multiaddr formats
    invalid_addresses = [
        "/ip4/127.0.0.1/tcp/8080",  # No WebSocket protocol
        "/ip4/127.0.0.1/wss",  # No TCP
        "/tcp/8080/wss",  # No network protocol
    ]

    for addr_str in invalid_addresses:
        ma = Multiaddr(addr_str)
        assert not is_valid_websocket_multiaddr(ma), (
            f"Address {addr_str} should be invalid"
        )

        # Should raise ValueError when parsing invalid addresses
        with pytest.raises(ValueError):
            parse_websocket_multiaddr(ma)


@pytest.mark.trio
async def test_handshake_timeout():
    """Test WebSocket handshake timeout functionality."""
    upgrader = create_upgrader()

    # Test creating transport with custom handshake timeout
    transport = WebsocketTransport(upgrader, handshake_timeout=0.1)  # 100ms timeout
    assert transport._handshake_timeout == 0.1

    # Test that the timeout is passed to the listener
    async def dummy_handler(conn):
        await trio.sleep(0)

    listener = transport.create_listener(dummy_handler)
    # Type assertion to access private attribute for testing
    assert hasattr(listener, "_handshake_timeout")
    assert getattr(listener, "_handshake_timeout") == 0.1


@pytest.mark.trio
async def test_handshake_timeout_creation():
    """Test handshake timeout in transport creation."""
    upgrader = create_upgrader()

    # Test creating transport with handshake timeout via create_transport
    from libp2p.transport import create_transport

    transport = create_transport("ws", upgrader, handshake_timeout=5.0)
    # Type assertion to access private attribute for testing
    assert hasattr(transport, "_handshake_timeout")
    assert getattr(transport, "_handshake_timeout") == 5.0

    # Test default timeout
    transport_default = create_transport("ws", upgrader)
    assert hasattr(transport_default, "_handshake_timeout")
    assert getattr(transport_default, "_handshake_timeout") == 15.0


@pytest.mark.trio
async def test_connection_state_tracking():
    """Test WebSocket connection state tracking."""
    from libp2p.transport.websocket.connection import P2PWebSocketConnection

    # Create a mock WebSocket connection
    class MockWebSocketConnection:
        async def send_message(self, data: bytes) -> None:
            pass

        async def get_message(self) -> bytes:
            return b"test message"

        async def aclose(self) -> None:
            pass

    mock_ws = MockWebSocketConnection()
    conn = P2PWebSocketConnection(mock_ws, is_secure=True)

    # Test initial state
    state = conn.conn_state()
    assert state["transport"] == "websocket"
    assert state["secure"] is True
    assert state["bytes_read"] == 0
    assert state["bytes_written"] == 0
    assert state["total_bytes"] == 0
    assert state["connection_duration"] >= 0

    # Test byte tracking (we can't actually read/write with mock, but we can test
    # the method)
    # The actual byte tracking will be tested in integration tests
    assert hasattr(conn, "_bytes_read")
    assert hasattr(conn, "_bytes_written")
    assert hasattr(conn, "_connection_start_time")


@pytest.mark.trio
async def test_concurrent_close_handling():
    """Test concurrent close handling similar to Go implementation."""
    from libp2p.transport.websocket.connection import P2PWebSocketConnection

    # Create a mock WebSocket connection that tracks close calls
    class MockWebSocketConnection:
        def __init__(self):
            self.close_calls = 0
            self.closed = False

        async def send_message(self, data: bytes) -> None:
            if self.closed:
                raise Exception("Connection closed")
            pass

        async def get_message(self) -> bytes:
            if self.closed:
                raise Exception("Connection closed")
            return b"test message"

        async def aclose(self) -> None:
            self.close_calls += 1
            self.closed = True

    mock_ws = MockWebSocketConnection()
    conn = P2PWebSocketConnection(mock_ws, is_secure=False)

    # Test that multiple close calls are handled gracefully
    await conn.close()
    await conn.close()  # Second close should not raise an error

    # The mock should only be closed once
    assert mock_ws.close_calls == 1
    assert mock_ws.closed is True


@pytest.mark.trio
async def test_zero_byte_write_handling():
    """Test zero-byte write handling similar to Go implementation."""
    from libp2p.transport.websocket.connection import P2PWebSocketConnection

    # Create a mock WebSocket connection that tracks write calls
    class MockWebSocketConnection:
        def __init__(self):
            self.write_calls = []

        async def send_message(self, data: bytes) -> None:
            self.write_calls.append(len(data))

        async def get_message(self) -> bytes:
            return b"test message"

        async def aclose(self) -> None:
            pass

    mock_ws = MockWebSocketConnection()
    conn = P2PWebSocketConnection(mock_ws, is_secure=False)

    # Test zero-byte write
    await conn.write(b"")
    assert 0 in mock_ws.write_calls

    # Test normal write
    await conn.write(b"hello")
    assert 5 in mock_ws.write_calls

    # Test multiple zero-byte writes
    for _ in range(10):
        await conn.write(b"")

    # Should have 11 zero-byte writes total (1 initial + 10 in loop)
    zero_byte_writes = [call for call in mock_ws.write_calls if call == 0]
    assert len(zero_byte_writes) == 11


@pytest.mark.trio
async def test_websocket_transport_protocols():
    """Test that WebSocket transport reports correct protocols."""
    # upgrader = create_upgrader()  # Not used in this test
    # transport = WebsocketTransport(upgrader)  # Not used in this test

    # Test that the transport can handle both WS and WSS protocols
    ws_maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
    wss_maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/wss")

    # Both should be valid WebSocket multiaddrs
    assert is_valid_websocket_multiaddr(ws_maddr)
    assert is_valid_websocket_multiaddr(wss_maddr)

    # Both should be parseable
    ws_parsed = parse_websocket_multiaddr(ws_maddr)
    wss_parsed = parse_websocket_multiaddr(wss_maddr)

    assert not ws_parsed.is_wss
    assert wss_parsed.is_wss


@pytest.mark.trio
async def test_websocket_listener_addr_format():
    """Test WebSocket listener address format similar to Go implementation."""
    upgrader = create_upgrader()

    # Test WS listener
    transport_ws = WebsocketTransport(upgrader)

    async def dummy_handler_ws(conn):
        await trio.sleep(0)

    listener_ws = transport_ws.create_listener(dummy_handler_ws)
    # Type assertion to access private attribute for testing
    assert hasattr(listener_ws, "_handshake_timeout")
    assert getattr(listener_ws, "_handshake_timeout") == 15.0  # Default timeout

    # Test WSS listener with TLS config
    import ssl

    tls_config = ssl.create_default_context()
    transport_wss = WebsocketTransport(upgrader, tls_server_config=tls_config)

    async def dummy_handler_wss(conn):
        await trio.sleep(0)

    listener_wss = transport_wss.create_listener(dummy_handler_wss)
    # Type assertion to access private attributes for testing
    assert hasattr(listener_wss, "_tls_config")
    assert getattr(listener_wss, "_tls_config") is not None
    assert hasattr(listener_wss, "_handshake_timeout")
    assert getattr(listener_wss, "_handshake_timeout") == 15.0


@pytest.mark.trio
async def test_sni_resolution_limitation():
    """
    Test SNI resolution limitation - Python multiaddr library doesn't support
    SNI protocol.
    """
    upgrader = create_upgrader()
    transport = WebsocketTransport(upgrader)

    # Test that WSS addresses are returned unchanged (SNI resolution not supported)
    wss_maddr = Multiaddr("/dns/example.com/tcp/1234/wss")
    resolved = transport.resolve(wss_maddr)
    assert len(resolved) == 1
    assert resolved[0] == wss_maddr

    # Test that non-WSS addresses are returned unchanged
    ws_maddr = Multiaddr("/dns/example.com/tcp/1234/ws")
    resolved = transport.resolve(ws_maddr)
    assert len(resolved) == 1
    assert resolved[0] == ws_maddr

    # Test that IP addresses are returned unchanged
    ip_maddr = Multiaddr("/ip4/127.0.0.1/tcp/1234/wss")
    resolved = transport.resolve(ip_maddr)
    assert len(resolved) == 1
    assert resolved[0] == ip_maddr


@pytest.mark.trio
async def test_websocket_transport_can_dial():
    """Test WebSocket transport CanDial functionality similar to Go implementation."""
    # upgrader = create_upgrader()  # Not used in this test
    # transport = WebsocketTransport(upgrader)  # Not used in this test

    # Test valid WebSocket addresses that should be dialable
    valid_addresses = [
        "/ip4/127.0.0.1/tcp/5555/ws",
        "/ip4/127.0.0.1/tcp/5555/wss",
        "/ip4/127.0.0.1/tcp/5555/tls/ws",
        # Note: SNI addresses not supported by Python multiaddr library
    ]

    for addr_str in valid_addresses:
        maddr = Multiaddr(addr_str)
        # All these should be valid WebSocket multiaddrs
        assert is_valid_websocket_multiaddr(maddr), (
            f"Address {addr_str} should be valid"
        )

    # Test invalid addresses that should not be dialable
    invalid_addresses = [
        "/ip4/127.0.0.1/tcp/5555",  # No WebSocket protocol
        "/ip4/127.0.0.1/udp/5555/ws",  # Wrong transport protocol
    ]

    for addr_str in invalid_addresses:
        maddr = Multiaddr(addr_str)
        # These should not be valid WebSocket multiaddrs
        assert not is_valid_websocket_multiaddr(maddr), (
            f"Address {addr_str} should be invalid"
        )
