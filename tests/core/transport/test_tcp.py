import logging

import pytest
import multiaddr
from multiaddr import (
    Multiaddr,
)
import trio

from examples.ping.ping import PING_LENGTH, PING_PROTOCOL_ID
from libp2p import new_host
from libp2p.abc import INetStream
from libp2p.network.connection.raw_connection import (
    RawConnection,
)
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.constants import (
    LISTEN_MADDR,
)
from libp2p.transport.exceptions import (
    OpenConnectionError,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)
from libp2p.utils.multiaddr_utils import (
    extract_ip_from_multiaddr,
    get_ip_protocol_from_multiaddr,
)

logger = logging.getLogger(__name__)


@pytest.mark.trio
async def test_tcp_listener(nursery):
    transport = TCP()

    async def handler(tcp_stream):
        pass

    listener = transport.create_listener(handler)
    assert len(listener.get_addrs()) == 0
    await listener.listen(LISTEN_MADDR, nursery)
    assert len(listener.get_addrs()) == 1
    await listener.listen(LISTEN_MADDR, nursery)
    assert len(listener.get_addrs()) == 2


@pytest.mark.trio
async def test_tcp_dial(nursery):
    transport = TCP()
    raw_conn_other_side: RawConnection | None = None
    event = trio.Event()

    async def handler(tcp_stream):
        nonlocal raw_conn_other_side
        raw_conn_other_side = RawConnection(tcp_stream, False)
        event.set()
        await trio.sleep_forever()

    # Test: `OpenConnectionError` is raised when trying to dial to a port which
    #   no one is not listening to.
    with pytest.raises(OpenConnectionError):
        await transport.dial(Multiaddr("/ip4/127.0.0.1/tcp/1"))

    listener = transport.create_listener(handler)
    await listener.listen(LISTEN_MADDR, nursery)
    addrs = listener.get_addrs()
    assert len(addrs) == 1
    listen_addr = addrs[0]
    raw_conn = await transport.dial(listen_addr)
    await event.wait()

    data = b"123"
    assert raw_conn_other_side is not None
    await raw_conn_other_side.write(data)
    assert (await raw_conn.read(len(data))) == data


@pytest.mark.trio
@pytest.mark.flaky(reruns=3, reruns_delay=2)
async def test_tcp_yamux_stress_ping():
    """TCP + Yamux version of stress ping test for comparison with QUIC."""
    STREAM_COUNT = 100
    listen_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
    latencies = []
    failures = []
    completion_event = trio.Event()
    completed_count: list[int] = [0]  # Use list to make it mutable for closures
    completed_lock = trio.Lock()

    # === Server Setup ===
    server_host = new_host(listen_addrs=[listen_addr])

    async def handle_ping(stream: INetStream) -> None:
        try:
            while True:
                payload = await stream.read(PING_LENGTH)
                if not payload:
                    break
                await stream.write(payload)
        except Exception:
            await stream.reset()

    server_host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

    async with server_host.run(listen_addrs=[listen_addr]):
        # Wait for server to actually be listening
        while not server_host.get_addrs():
            await trio.sleep(0.01)

        # === Client Setup ===
        destination = str(server_host.get_addrs()[0])
        maddr = multiaddr.Multiaddr(destination)
        info = info_from_p2p_addr(maddr)

        client_listen_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
        client_host = new_host(listen_addrs=[client_listen_addr])

        async with client_host.run(listen_addrs=[client_listen_addr]):
            await client_host.connect(info)

            # Wait for connection to be established and ready
            network = client_host.get_network()
            connections_map = network.get_connections_map()
            while (
                info.peer_id not in connections_map or not connections_map[info.peer_id]
            ):
                await trio.sleep(0.01)
                connections_map = network.get_connections_map()

            # Wait for connection's event_started to ensure it's ready for streams
            connections = connections_map[info.peer_id]
            if connections:
                swarm_conn = connections[0]
                if hasattr(swarm_conn, "event_started"):
                    await swarm_conn.event_started.wait()
                await trio.sleep(0.05)

            async def ping_stream(i: int):
                stream = None
                try:
                    start = trio.current_time()

                    stream = await client_host.new_stream(
                        info.peer_id, [PING_PROTOCOL_ID]
                    )

                    await stream.write(b"\x01" * PING_LENGTH)

                    with trio.fail_after(30):
                        response = await stream.read(PING_LENGTH)

                    if response == b"\x01" * PING_LENGTH:
                        latency_ms = int((trio.current_time() - start) * 1000)
                        latencies.append(latency_ms)
                        print(f"[TCP Ping #{i}] Latency: {latency_ms} ms")
                    await stream.close()
                except Exception as e:
                    print(f"[TCP Ping #{i}] Failed: {e}")
                    failures.append(i)
                    if stream:
                        try:
                            await stream.reset()
                        except Exception:
                            pass
                finally:
                    async with completed_lock:
                        completed_count[0] += 1
                        if completed_count[0] == STREAM_COUNT:
                            completion_event.set()

            # No semaphore limit - run all streams concurrently
            async with trio.open_nursery() as nursery:
                for i in range(STREAM_COUNT):
                    nursery.start_soon(ping_stream, i)

                with trio.fail_after(120):
                    await completion_event.wait()

        # === Result Summary ===
        logger.info("TCP Ping Stress Test Summary")
        logger.info(f"Total Streams Launched: {STREAM_COUNT}")
        logger.info(f"Successful Pings: {len(latencies)}")
        logger.info(f"Failed Pings: {len(failures)}")
        if failures:
            logger.warning(f"Failed stream indices: {failures}")

        # === Assertions ===
        assert len(latencies) == STREAM_COUNT, (
            f"Expected {STREAM_COUNT} successful streams, got {len(latencies)}"
        )
        assert all(isinstance(x, int) and x >= 0 for x in latencies), (
            "Invalid latencies"
        )

        avg_latency = sum(latencies) / len(latencies)
        logger.info(f"Average Latency: {avg_latency:.2f} ms")
        assert avg_latency < 1000


@pytest.mark.trio
async def test_ipv6_tcp_can_parse_address():
    """Test that IPv6 addresses can be parsed without hanging."""
    maddr = Multiaddr("/ip6/::1/tcp/4001")

    ip = extract_ip_from_multiaddr(maddr)
    assert ip == "::1"

    protocol = get_ip_protocol_from_multiaddr(maddr)
    assert protocol == "ip6"


@pytest.mark.trio
async def test_ipv6_tcp_dial_fails_on_nonexistent_server():
    """
    Test that IPv6 dial attempts work (expected to fail for non-existent server).
    """
    transport = TCP()

    try:
        await transport.dial(Multiaddr("/ip6/::1/tcp/1"))
        assert False, "Should have raised OpenConnectionError"
    except Exception as e:
        assert "Failed to open TCP stream" in str(e) or "Failed to dial" in str(e)


@pytest.mark.trio
@pytest.mark.skip(
    reason="IPv6 listener hangs - trio.serve_tcp may need IPv6-specific configuration"
)
# TODO: Open follow-up issue to re-enable when IPv6 listen/dial is stable
async def test_ipv6_tcp_listen_and_dial(nursery):
    """Test that TCP transport can listen and dial using IPv6 addresses."""
    transport = TCP()
    raw_conn_other_side: RawConnection | None = None
    event = trio.Event()

    async def handler(tcp_stream):
        nonlocal raw_conn_other_side
        raw_conn_other_side = RawConnection(tcp_stream, False)
        event.set()
        await trio.sleep_forever()

    # Listen on IPv6 loopback
    listen_addr = Multiaddr("/ip6/::1/tcp/0")
    listener = transport.create_listener(handler)
    await listener.listen(listen_addr, nursery)
    addrs = listener.get_addrs()
    assert len(addrs) == 1

    # Verify that the address is IPv6
    listen_addr = addrs[0]
    protocol = get_ip_protocol_from_multiaddr(listen_addr)
    assert protocol == "ip6", f"Expected ip6 protocol, got {protocol}"

    # Dial to IPv6 address
    raw_conn = await transport.dial(listen_addr)
    await event.wait()

    # Test data transfer
    data = b"test_ipv6_data"
    assert raw_conn_other_side is not None
    await raw_conn_other_side.write(data)
    assert (await raw_conn.read(len(data))) == data


@pytest.mark.trio
async def test_ipv6_tcp_dial_with_ipv4_fallback(nursery):
    """Test that IPv4 addresses still work alongside IPv6."""
    transport = TCP()
    raw_conn_other_side: RawConnection | None = None
    event = trio.Event()

    async def handler(tcp_stream):
        nonlocal raw_conn_other_side
        raw_conn_other_side = RawConnection(tcp_stream, False)
        event.set()
        await trio.sleep_forever()

    # Listen on IPv4 loopback
    listen_addr = Multiaddr("/ip4/127.0.0.1/tcp/0")
    listener = transport.create_listener(handler)
    await listener.listen(listen_addr, nursery)
    addrs = listener.get_addrs()
    assert len(addrs) == 1

    # Verify that the address is IPv4
    listen_addr = addrs[0]
    protocol = get_ip_protocol_from_multiaddr(listen_addr)
    assert protocol == "ip4", f"Expected ip4 protocol, got {protocol}"

    # Dial to IPv4 address (should still work)
    raw_conn = await transport.dial(listen_addr)
    await event.wait()

    # Test data transfer
    data = b"test_ipv4_data"
    assert raw_conn_other_side is not None
    await raw_conn_other_side.write(data)
    assert (await raw_conn.read(len(data))) == data


def test_extract_ip_from_multiaddr():
    """Test the extract_ip_from_multiaddr helper function."""
    # IPv4 address
    maddr_ipv4 = Multiaddr("/ip4/127.0.0.1/tcp/4001")
    ip = extract_ip_from_multiaddr(maddr_ipv4)
    assert ip == "127.0.0.1"

    # IPv6 address
    maddr_ipv6 = Multiaddr("/ip6/::1/tcp/4001")
    ip = extract_ip_from_multiaddr(maddr_ipv6)
    assert ip == "::1"

    # Multiaddr without IP should return None
    maddr_no_ip = Multiaddr("/tcp/4001")
    ip = extract_ip_from_multiaddr(maddr_no_ip)
    assert ip is None


def test_get_ip_protocol_from_multiaddr():
    """Test the get_ip_protocol_from_multiaddr helper function."""
    # IPv4 address
    maddr_ipv4 = Multiaddr("/ip4/127.0.0.1/tcp/4001")
    protocol = get_ip_protocol_from_multiaddr(maddr_ipv4)
    assert protocol == "ip4"

    # IPv6 address
    maddr_ipv6 = Multiaddr("/ip6/::1/tcp/4001")
    protocol = get_ip_protocol_from_multiaddr(maddr_ipv6)
    assert protocol == "ip6"

    # Multiaddr without IP should return None
    maddr_no_ip = Multiaddr("/tcp/4001")
    protocol = get_ip_protocol_from_multiaddr(maddr_no_ip)
    assert protocol is None
