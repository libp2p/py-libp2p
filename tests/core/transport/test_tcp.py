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
        print("\n📊 TCP Ping Stress Test Summary")
        print(f"Total Streams Launched: {STREAM_COUNT}")
        print(f"Successful Pings: {len(latencies)}")
        print(f"Failed Pings: {len(failures)}")
        if failures:
            print(f"❌ Failed stream indices: {failures}")

        # === Assertions ===
        assert len(latencies) == STREAM_COUNT, (
            f"Expected {STREAM_COUNT} successful streams, got {len(latencies)}"
        )
        assert all(isinstance(x, int) and x >= 0 for x in latencies), (
            "Invalid latencies"
        )

        avg_latency = sum(latencies) / len(latencies)
        print(f"✅ Average Latency: {avg_latency:.2f} ms")
        assert avg_latency < 1000
