import pytest
from multiaddr import (
    Multiaddr,
)
import trio
from trio.testing import (
    wait_all_tasks_blocked,
)

from libp2p import (
    new_swarm,
)
from libp2p.network.exceptions import (
    SwarmException,
)
from libp2p.network.swarm import (
    Swarm,
)
from libp2p.tools.async_service import (
    background_trio_service,
)
from libp2p.tools.utils import (
    connect_swarm,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)
from tests.utils.factories import (
    SwarmFactory,
)


@pytest.mark.trio
async def test_swarm_dial_peer(security_protocol):
    async with SwarmFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as swarms:
        # Test: No addr found.
        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        # Test: len(addr) in the peerstore is 0.
        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), [], 10000)
        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        # Test: Succeed if addrs of the peer_id are present in the peerstore.
        addrs = tuple(
            addr
            for transport in swarms[1].listeners.values()
            for addr in transport.get_addrs()
        )
        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), addrs, 10000)

        # New: dial_peer now returns list of connections
        connections = await swarms[0].dial_peer(swarms[1].get_peer_id())
        assert len(connections) > 0

        # Verify connections are established in both directions
        assert swarms[0].get_peer_id() in swarms[1].connections
        assert swarms[1].get_peer_id() in swarms[0].connections

        # Test: Reuse connections when we already have ones with a peer.
        existing_connections = swarms[0].get_connections(swarms[1].get_peer_id())
        new_connections = await swarms[0].dial_peer(swarms[1].get_peer_id())
        assert new_connections == existing_connections


@pytest.mark.trio
async def test_swarm_close_peer(security_protocol):
    async with SwarmFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as swarms:
        # 0 <> 1 <> 2
        await connect_swarm(swarms[0], swarms[1])
        await connect_swarm(swarms[1], swarms[2])

        # peer 1 closes peer 0
        await swarms[1].close_peer(swarms[0].get_peer_id())
        await trio.sleep(0.01)
        await wait_all_tasks_blocked()
        # 0  1 <> 2
        assert len(swarms[0].connections) == 0
        assert (
            len(swarms[1].connections) == 1
            and swarms[2].get_peer_id() in swarms[1].connections
        )

        # peer 1 is closed by peer 2
        await swarms[2].close_peer(swarms[1].get_peer_id())
        await trio.sleep(0.01)
        # 0  1  2
        assert len(swarms[1].connections) == 0 and len(swarms[2].connections) == 0

        await connect_swarm(swarms[0], swarms[1])
        # 0 <> 1  2
        assert (
            len(swarms[0].connections) == 1
            and swarms[1].get_peer_id() in swarms[0].connections
        )
        assert (
            len(swarms[1].connections) == 1
            and swarms[0].get_peer_id() in swarms[1].connections
        )
        # peer 0 closes peer 1
        await swarms[0].close_peer(swarms[1].get_peer_id())
        await trio.sleep(0.01)
        # 0  1  2
        assert len(swarms[1].connections) == 0 and len(swarms[2].connections) == 0


@pytest.mark.trio
async def test_swarm_remove_conn(swarm_pair):
    swarm_0, swarm_1 = swarm_pair
    # Get the first connection from the list
    conn_0 = swarm_0.connections[swarm_1.get_peer_id()][0]
    swarm_0.remove_conn(conn_0)
    assert swarm_1.get_peer_id() not in swarm_0.connections
    # Test: Remove twice. There should not be errors.
    swarm_0.remove_conn(conn_0)
    assert swarm_1.get_peer_id() not in swarm_0.connections


@pytest.mark.trio
async def test_swarm_multiple_connections(security_protocol):
    """Test multiple connections per peer functionality."""
    async with SwarmFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as swarms:
        # Setup multiple addresses for peer
        addrs = tuple(
            addr
            for transport in swarms[1].listeners.values()
            for addr in transport.get_addrs()
        )
        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), addrs, 10000)

        # Dial peer - should return list of connections
        connections = await swarms[0].dial_peer(swarms[1].get_peer_id())
        assert len(connections) > 0

        # Test get_connections method
        peer_connections = swarms[0].get_connections(swarms[1].get_peer_id())
        assert len(peer_connections) == len(connections)

        # Test get_connections_map method
        connections_map = swarms[0].get_connections_map()
        assert swarms[1].get_peer_id() in connections_map
        assert len(connections_map[swarms[1].get_peer_id()]) == len(connections)

        # Test get_connection method (backward compatibility)
        single_conn = swarms[0].get_connection(swarms[1].get_peer_id())
        assert single_conn is not None
        assert single_conn in connections


@pytest.mark.trio
async def test_swarm_load_balancing(security_protocol):
    """Test load balancing across multiple connections."""
    async with SwarmFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as swarms:
        # Setup connection
        addrs = tuple(
            addr
            for transport in swarms[1].listeners.values()
            for addr in transport.get_addrs()
        )
        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), addrs, 10000)

        # Create multiple streams - should use load balancing
        streams = []
        for _ in range(5):
            stream = await swarms[0].new_stream(swarms[1].get_peer_id())
            streams.append(stream)

        # Verify streams were created successfully
        assert len(streams) == 5

        # Clean up
        for stream in streams:
            await stream.close()


@pytest.mark.trio
async def test_swarm_multiaddr(security_protocol):
    async with SwarmFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as swarms:

        def clear():
            swarms[0].peerstore.clear_addrs(swarms[1].get_peer_id())

        clear()
        # No addresses
        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        clear()
        # Wrong addresses
        swarms[0].peerstore.add_addrs(
            swarms[1].get_peer_id(), [Multiaddr("/ip4/0.0.0.0/tcp/9999")], 10000
        )

        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        clear()
        # Multiple wrong addresses
        swarms[0].peerstore.add_addrs(
            swarms[1].get_peer_id(),
            [Multiaddr("/ip4/0.0.0.0/tcp/9999"), Multiaddr("/ip4/0.0.0.0/tcp/9998")],
            10000,
        )

        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        # Test one address
        addrs = tuple(
            addr
            for transport in swarms[1].listeners.values()
            for addr in transport.get_addrs()
        )

        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), addrs[:1], 10000)
        await swarms[0].dial_peer(swarms[1].get_peer_id())

        # Test multiple addresses
        addrs = tuple(
            addr
            for transport in swarms[1].listeners.values()
            for addr in transport.get_addrs()
        )

        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), addrs + addrs, 10000)
        await swarms[0].dial_peer(swarms[1].get_peer_id())


def test_new_swarm_defaults_to_tcp():
    swarm = new_swarm()
    assert isinstance(swarm, Swarm)
    assert isinstance(swarm.transport, TCP)


def test_new_swarm_tcp_multiaddr_supported():
    addr = Multiaddr("/ip4/127.0.0.1/tcp/9999")
    swarm = new_swarm(listen_addrs=[addr])
    assert isinstance(swarm, Swarm)
    assert isinstance(swarm.transport, TCP)


def test_new_swarm_quic_multiaddr_supported():
    from libp2p.transport.quic.transport import QUICTransport

    addr = Multiaddr("/ip4/127.0.0.1/udp/9999/quic")
    swarm = new_swarm(listen_addrs=[addr])
    assert isinstance(swarm, Swarm)
    assert isinstance(swarm.transport, QUICTransport)


@pytest.mark.trio
async def test_swarm_listen_multiple_addresses(security_protocol):
    """Test that swarm can listen on multiple addresses simultaneously."""
    from libp2p.utils.address_validation import get_available_interfaces

    # Get multiple addresses to listen on
    listen_addrs = get_available_interfaces(0)  # Let OS choose ports

    # Create a swarm and listen on multiple addresses
    swarm = SwarmFactory.build(security_protocol=security_protocol)
    async with background_trio_service(swarm):
        # Listen on all addresses
        success = await swarm.listen(*listen_addrs)
        assert success, "Should successfully listen on at least one address"

        # Check that we have listeners for the addresses
        actual_listeners = list(swarm.listeners.keys())
        assert len(actual_listeners) > 0, "Should have at least one listener"

        # Verify that all successful listeners are in the listeners dict
        successful_count = 0
        for addr in listen_addrs:
            addr_str = str(addr)
            if addr_str in actual_listeners:
                successful_count += 1
                # This address successfully started listening
                listener = swarm.listeners[addr_str]
                listener_addrs = listener.get_addrs()
                assert len(listener_addrs) > 0, (
                    f"Listener for {addr} should have addresses"
                )

                # Check that the listener address matches the expected address
                # (port might be different if we used port 0)
                expected_ip = addr.value_for_protocol("ip4")
                expected_protocol = addr.value_for_protocol("tcp")
                if expected_ip and expected_protocol:
                    found_matching = False
                    for listener_addr in listener_addrs:
                        if (
                            listener_addr.value_for_protocol("ip4") == expected_ip
                            and listener_addr.value_for_protocol("tcp") is not None
                        ):
                            found_matching = True
                            break
                    assert found_matching, (
                        f"Listener for {addr} should have matching IP"
                    )

        assert successful_count == len(listen_addrs), (
            f"All {len(listen_addrs)} addresses should be listening, "
            f"but only {successful_count} succeeded"
        )


@pytest.mark.trio
async def test_swarm_listen_multiple_addresses_connectivity(security_protocol):
    """Test that real libp2p connections can be established to all listening addresses."""  # noqa: E501
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.utils.address_validation import get_available_interfaces

    # Get multiple addresses to listen on
    listen_addrs = get_available_interfaces(0)  # Let OS choose ports

    # Create a swarm and listen on multiple addresses
    swarm1 = SwarmFactory.build(security_protocol=security_protocol)
    async with background_trio_service(swarm1):
        # Listen on all addresses
        success = await swarm1.listen(*listen_addrs)
        assert success, "Should successfully listen on at least one address"

        # Verify all available interfaces are listening
        assert len(swarm1.listeners) == len(listen_addrs), (
            f"All {len(listen_addrs)} interfaces should be listening, "
            f"but only {len(swarm1.listeners)} are"
        )

        # Create a second swarm to test connections
        swarm2 = SwarmFactory.build(security_protocol=security_protocol)
        async with background_trio_service(swarm2):
            # Test connectivity to each listening address using real libp2p connections
            for addr_str, listener in swarm1.listeners.items():
                listener_addrs = listener.get_addrs()
                for listener_addr in listener_addrs:
                    # Create a full multiaddr with peer ID for libp2p connection
                    peer_id = swarm1.get_peer_id()
                    full_addr = listener_addr.encapsulate(f"/p2p/{peer_id}")

                    # Test real libp2p connection
                    try:
                        peer_info = info_from_p2p_addr(full_addr)

                        # Add the peer info to swarm2's peerstore so it knows where to connect  # noqa: E501
                        swarm2.peerstore.add_addrs(
                            peer_info.peer_id, [listener_addr], 10000
                        )

                        await swarm2.dial_peer(peer_info.peer_id)

                        # Verify connection was established
                        assert peer_info.peer_id in swarm2.connections, (
                            f"Connection to {full_addr} should be established"
                        )
                        assert swarm2.get_peer_id() in swarm1.connections, (
                            f"Connection from {full_addr} should be established"
                        )

                    except Exception as e:
                        pytest.fail(
                            f"Failed to establish libp2p connection to {full_addr}: {e}"
                        )
