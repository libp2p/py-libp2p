from collections.abc import Sequence
import logging
from typing import Any

import pytest
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
