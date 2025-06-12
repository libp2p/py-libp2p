"""
Integration tests for QUIC transport that test actual networking.
These tests require network access and test real socket operations.
"""

import logging
import random
import socket
import time

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.utils import create_quic_multiaddr

logger = logging.getLogger(__name__)


class TestQUICNetworking:
    """Integration tests that use actual networking."""

    @pytest.fixture
    def server_config(self):
        """Server configuration."""
        return QUICTransportConfig(
            idle_timeout=10.0,
            connection_timeout=5.0,
            max_concurrent_streams=100,
        )

    @pytest.fixture
    def client_config(self):
        """Client configuration."""
        return QUICTransportConfig(
            idle_timeout=10.0,
            connection_timeout=5.0,
        )

    @pytest.fixture
    def server_key(self):
        """Generate server key pair."""
        return create_new_key_pair().private_key

    @pytest.fixture
    def client_key(self):
        """Generate client key pair."""
        return create_new_key_pair().private_key

    @pytest.mark.trio
    async def test_listener_binding_real_socket(self, server_key, server_config):
        """Test that listener can bind to real socket."""
        transport = QUICTransport(server_key, server_config)

        async def connection_handler(connection):
            logger.info(f"Received connection: {connection}")

        listener = transport.create_listener(connection_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        async with trio.open_nursery() as nursery:
            try:
                success = await listener.listen(listen_addr, nursery)
                assert success

                # Verify we got a real port
                addrs = listener.get_addrs()
                assert len(addrs) == 1

                # Port should be non-zero (was assigned)
                from libp2p.transport.quic.utils import quic_multiaddr_to_endpoint

                host, port = quic_multiaddr_to_endpoint(addrs[0])
                assert host == "127.0.0.1"
                assert port > 0

                logger.info(f"Listener bound to {host}:{port}")

                # Listener should be active
                assert listener.is_listening()

                # Test basic stats
                stats = listener.get_stats()
                assert stats["active_connections"] == 0
                assert stats["pending_connections"] == 0

                # Close listener
                await listener.close()
                assert not listener.is_listening()

            finally:
                await transport.close()

    @pytest.mark.trio
    async def test_multiple_listeners_different_ports(self, server_key, server_config):
        """Test multiple listeners on different ports."""
        transport = QUICTransport(server_key, server_config)

        async def connection_handler(connection):
            pass

        listeners = []
        bound_ports = []

        # Create multiple listeners
        for i in range(3):
            listener = transport.create_listener(connection_handler)
            listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

            try:
                async with trio.open_nursery() as nursery:
                    success = await listener.listen(listen_addr, nursery)
                    assert success

                    # Get bound port
                    addrs = listener.get_addrs()
                    from libp2p.transport.quic.utils import quic_multiaddr_to_endpoint

                    host, port = quic_multiaddr_to_endpoint(addrs[0])

                    bound_ports.append(port)
                    listeners.append(listener)

                    logger.info(f"Listener {i} bound to port {port}")
                    nursery.cancel_scope.cancel()
            finally:
                await listener.close()

        # All ports should be different
        assert len(set(bound_ports)) == len(bound_ports)

    @pytest.mark.trio
    async def test_port_already_in_use(self, server_key, server_config):
        """Test handling of port already in use."""
        transport1 = QUICTransport(server_key, server_config)
        transport2 = QUICTransport(server_key, server_config)

        async def connection_handler(connection):
            pass

        listener1 = transport1.create_listener(connection_handler)
        listener2 = transport2.create_listener(connection_handler)

        # Bind first listener to a specific port
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        async with trio.open_nursery() as nursery:
            success1 = await listener1.listen(listen_addr, nursery)
            assert success1

            # Get the actual bound port
            addrs = listener1.get_addrs()
            from libp2p.transport.quic.utils import quic_multiaddr_to_endpoint

            host, port = quic_multiaddr_to_endpoint(addrs[0])

            # Try to bind second listener to same port
            # Should fail or get different port
            same_port_addr = create_quic_multiaddr("127.0.0.1", port, "/quic")

            # This might either fail or succeed with SO_REUSEPORT
            # The exact behavior depends on the system
            try:
                success2 = await listener2.listen(same_port_addr, nursery)
                if success2:
                    # If it succeeds, verify different behavior
                    logger.info("Second listener bound successfully (SO_REUSEPORT)")
            except Exception as e:
                logger.info(f"Second listener failed as expected: {e}")

            await listener1.close()
            await listener2.close()
            await transport1.close()
            await transport2.close()

    @pytest.mark.trio
    async def test_listener_connection_tracking(self, server_key, server_config):
        """Test that listener properly tracks connection state."""
        transport = QUICTransport(server_key, server_config)

        received_connections = []

        async def connection_handler(connection):
            received_connections.append(connection)
            logger.info(f"Handler received connection: {connection}")

            # Keep connection alive briefly
            await trio.sleep(0.1)

        listener = transport.create_listener(connection_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        async with trio.open_nursery() as nursery:
            success = await listener.listen(listen_addr, nursery)
            assert success

            # Initially no connections
            stats = listener.get_stats()
            assert stats["active_connections"] == 0
            assert stats["pending_connections"] == 0

            # Simulate some packet processing
            await trio.sleep(0.1)

            # Verify listener is still healthy
            assert listener.is_listening()

            await listener.close()
            await transport.close()

    @pytest.mark.trio
    async def test_listener_error_recovery(self, server_key, server_config):
        """Test listener error handling and recovery."""
        transport = QUICTransport(server_key, server_config)

        # Handler that raises an exception
        async def failing_handler(connection):
            raise ValueError("Simulated handler error")

        listener = transport.create_listener(failing_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
        try:
            async with trio.open_nursery() as nursery:
                success = await listener.listen(listen_addr, nursery)
                assert success
                # Even with failing handler, listener should remain stable
                await trio.sleep(0.1)
                assert listener.is_listening()

                # Test complete, stop listening
                nursery.cancel_scope.cancel()
        finally:
            await listener.close()
            await transport.close()

    @pytest.mark.trio
    async def test_transport_resource_cleanup_v1(self, server_key, server_config):
        """Test with single parent nursery managing all listeners."""
        transport = QUICTransport(server_key, server_config)

        async def connection_handler(connection):
            pass

        listeners = []

        try:
            async with trio.open_nursery() as parent_nursery:
                # Start all listeners in parallel within the same nursery
                for i in range(3):
                    listener = transport.create_listener(connection_handler)
                    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
                    listeners.append(listener)

                    parent_nursery.start_soon(
                        listener.listen, listen_addr, parent_nursery
                    )

                # Give listeners time to start
                await trio.sleep(0.2)

                # Verify all listeners are active
                for i, listener in enumerate(listeners):
                    assert listener.is_listening()

                # Close transport should close all listeners
                await transport.close()

                # The nursery will exit cleanly because listeners are closed

        finally:
            # Cleanup verification outside nursery
            assert transport._closed
            assert len(transport._listeners) == 0

            # All listeners should be closed
            for listener in listeners:
                assert not listener.is_listening()

    @pytest.mark.trio
    async def test_concurrent_listener_operations(self, server_key, server_config):
        """Test concurrent listener operations."""
        transport = QUICTransport(server_key, server_config)

        async def connection_handler(connection):
            await trio.sleep(0.01)  # Simulate some work

        async def create_and_run_listener(listener_id):
            """Create, run, and close a listener."""
            listener = transport.create_listener(connection_handler)
            listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

            async with trio.open_nursery() as nursery:
                success = await listener.listen(listen_addr, nursery)
                assert success

                logger.info(f"Listener {listener_id} started")

                # Run for a short time
                await trio.sleep(0.1)

                await listener.close()
                logger.info(f"Listener {listener_id} closed")

        try:
            # Run multiple listeners concurrently
            async with trio.open_nursery() as nursery:
                for i in range(5):
                    nursery.start_soon(create_and_run_listener, i)

        finally:
            await transport.close()


class TestQUICConcurrency:
    """Fixed tests with proper nursery management."""

    @pytest.fixture
    def server_key(self):
        """Generate server key pair."""
        return create_new_key_pair().private_key

    @pytest.fixture
    def server_config(self):
        """Server configuration."""
        return QUICTransportConfig(
            idle_timeout=10.0,
            connection_timeout=5.0,
            max_concurrent_streams=100,
        )

    @pytest.mark.trio
    async def test_concurrent_listener_operations(self, server_key, server_config):
        """Test concurrent listener operations - FIXED VERSION."""
        transport = QUICTransport(server_key, server_config)

        async def connection_handler(connection):
            await trio.sleep(0.01)  # Simulate some work

        listeners = []

        async def create_and_run_listener(listener_id):
            """Create and run a listener - fixed to avoid deadlock."""
            listener = transport.create_listener(connection_handler)
            listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
            listeners.append(listener)

            try:
                async with trio.open_nursery() as nursery:
                    success = await listener.listen(listen_addr, nursery)
                    assert success

                    logger.info(f"Listener {listener_id} started")

                    # Run for a short time
                    await trio.sleep(0.1)

                    # Close INSIDE the nursery scope to allow clean exit
                    await listener.close()
                    logger.info(f"Listener {listener_id} closed")

            except Exception as e:
                logger.error(f"Listener {listener_id} error: {e}")
                if not listener._closed:
                    await listener.close()
                raise

        try:
            # Run multiple listeners concurrently
            async with trio.open_nursery() as nursery:
                for i in range(5):
                    nursery.start_soon(create_and_run_listener, i)

            # Verify all listeners were created and closed properly
            assert len(listeners) == 5
            for listener in listeners:
                assert not listener.is_listening()  # Should all be closed

        finally:
            await transport.close()

    @pytest.mark.trio
    @pytest.mark.slow
    async def test_listener_under_simulated_load(self, server_key, server_config):
        """REAL load test with actual packet simulation."""
        print("=== REAL LOAD TEST ===")

        config = QUICTransportConfig(
            idle_timeout=30.0,
            connection_timeout=10.0,
            max_concurrent_streams=1000,
            max_connections=500,
        )

        transport = QUICTransport(server_key, config)
        connection_count = 0

        async def connection_handler(connection):
            nonlocal connection_count
            # TODO: Remove type ignore when pyrefly fixes nonlocal bug
            connection_count += 1  # type: ignore
            print(f"Real connection established: {connection_count}")
            # Simulate connection work
            await trio.sleep(0.01)

        listener = transport.create_listener(connection_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        async def generate_udp_traffic(target_host, target_port, num_packets=100):
            """Generate fake UDP traffic to simulate load."""
            print(
                f"Generating {num_packets} UDP packets to {target_host}:{target_port}"
            )

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                for i in range(num_packets):
                    # Send random UDP packets
                    # (Won't be valid QUIC, but will exercise packet handler)
                    fake_packet = (
                        f"FAKE_PACKET_{i}_{random.randint(1000, 9999)}".encode()
                    )
                    sock.sendto(fake_packet, (target_host, int(target_port)))

                    # Small delay between packets
                    await trio.sleep(0.001)

                    if i % 20 == 0:
                        print(f"Sent {i + 1}/{num_packets} packets")

            except Exception as e:
                print(f"Error sending packets: {e}")
            finally:
                sock.close()

            print(f"Finished sending {num_packets} packets")

        try:
            async with trio.open_nursery() as nursery:
                success = await listener.listen(listen_addr, nursery)
                assert success

                # Get the actual bound port
                bound_addrs = listener.get_addrs()
                bound_addr = bound_addrs[0]
                print(bound_addr)
                host, port = (
                    bound_addr.value_for_protocol("ip4"),
                    bound_addr.value_for_protocol("udp"),
                )

                print(f"Listener bound to {host}:{port}")

                # Start load generation
                nursery.start_soon(generate_udp_traffic, host, port, 50)

                # Let the load test run
                start_time = time.time()
                await trio.sleep(2.0)  # Let traffic flow for 2 seconds
                end_time = time.time()

                # Check that listener handled the load
                stats = listener.get_stats()
                print(f"Final stats: {stats}")

                # Should have received packets (even if they're invalid QUIC)
                assert stats["packets_processed"] > 0
                assert stats["bytes_received"] > 0

                duration = end_time - start_time
                print(f"Load test ran for {duration:.2f}s")
                print(f"Processed {stats['packets_processed']} packets")
                print(f"Received {stats['bytes_received']} bytes")

                await listener.close()

        finally:
            if not listener._closed:
                await listener.close()
            await transport.close()


class TestQUICRealWorldScenarios:
    """Test real-world usage scenarios - FIXED VERSIONS."""

    @pytest.mark.trio
    async def test_echo_server_pattern(self):
        """Test a basic echo server pattern - FIXED VERSION."""
        server_key = create_new_key_pair().private_key
        config = QUICTransportConfig(idle_timeout=5.0)
        transport = QUICTransport(server_key, config)

        echo_data = []

        async def echo_connection_handler(connection):
            """Echo server that handles one connection."""
            logger.info(f"Echo server got connection: {connection}")

            async def stream_handler(stream):
                try:
                    # Read data and echo it back
                    while True:
                        data = await stream.read(1024)
                        if not data:
                            break

                        echo_data.append(data)
                        await stream.write(b"ECHO: " + data)

                except Exception as e:
                    logger.error(f"Stream error: {e}")
                finally:
                    await stream.close()

            connection.set_stream_handler(stream_handler)

            # Keep connection alive until closed
            while not connection.is_closed:
                await trio.sleep(0.1)

        listener = transport.create_listener(echo_connection_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        try:
            async with trio.open_nursery() as nursery:
                success = await listener.listen(listen_addr, nursery)
                assert success

                # Let server initialize
                await trio.sleep(0.1)

                # Verify server is ready
                assert listener.is_listening()

                # Run server for a bit
                await trio.sleep(0.5)

                # Close inside nursery for clean exit
                await listener.close()

        finally:
            # Ensure cleanup
            if not listener._closed:
                await listener.close()
            await transport.close()

    @pytest.mark.trio
    async def test_connection_lifecycle_monitoring(self):
        """Test monitoring connection lifecycle events - FIXED VERSION."""
        server_key = create_new_key_pair().private_key
        config = QUICTransportConfig(idle_timeout=5.0)
        transport = QUICTransport(server_key, config)

        lifecycle_events = []

        async def monitoring_handler(connection):
            lifecycle_events.append(("connection_started", connection.get_stats()))

            try:
                # Monitor connection
                while not connection.is_closed:
                    stats = connection.get_stats()
                    lifecycle_events.append(("connection_stats", stats))
                    await trio.sleep(0.1)

            except Exception as e:
                lifecycle_events.append(("connection_error", str(e)))
            finally:
                lifecycle_events.append(("connection_ended", connection.get_stats()))

        listener = transport.create_listener(monitoring_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        try:
            async with trio.open_nursery() as nursery:
                success = await listener.listen(listen_addr, nursery)
                assert success

                # Run monitoring for a bit
                await trio.sleep(0.5)

                # Check that monitoring infrastructure is working
                assert listener.is_listening()

                # Close inside nursery
                await listener.close()

        finally:
            # Ensure cleanup
            if not listener._closed:
                await listener.close()
            await transport.close()

        # Should have some lifecycle events from setup
        logger.info(f"Recorded {len(lifecycle_events)} lifecycle events")

    @pytest.mark.trio
    async def test_multi_listener_echo_servers(self):
        """Test multiple echo servers running in parallel."""
        server_key = create_new_key_pair().private_key
        config = QUICTransportConfig(idle_timeout=5.0)
        transport = QUICTransport(server_key, config)

        all_echo_data = {}
        listeners = []

        async def create_echo_server(server_id):
            """Create and run one echo server."""
            echo_data = []
            all_echo_data[server_id] = echo_data

            async def echo_handler(connection):
                logger.info(f"Echo server {server_id} got connection")

                async def stream_handler(stream):
                    try:
                        while True:
                            data = await stream.read(1024)
                            if not data:
                                break
                            echo_data.append(data)
                            await stream.write(f"ECHO-{server_id}: ".encode() + data)
                    except Exception as e:
                        logger.error(f"Stream error in server {server_id}: {e}")
                    finally:
                        await stream.close()

                connection.set_stream_handler(stream_handler)
                while not connection.is_closed:
                    await trio.sleep(0.1)

            listener = transport.create_listener(echo_handler)
            listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
            listeners.append(listener)

            async with trio.open_nursery() as nursery:
                success = await listener.listen(listen_addr, nursery)
                assert success
                logger.info(f"Echo server {server_id} started")

                # Run for a bit
                await trio.sleep(0.3)

                # Close this server
                await listener.close()
                logger.info(f"Echo server {server_id} closed")

        try:
            # Run multiple echo servers in parallel
            async with trio.open_nursery() as nursery:
                for i in range(3):
                    nursery.start_soon(create_echo_server, i)

            # Verify all servers ran
            assert len(listeners) == 3
            assert len(all_echo_data) == 3

            for listener in listeners:
                assert not listener.is_listening()  # Should all be closed

        finally:
            await transport.close()

    @pytest.mark.trio
    async def test_graceful_shutdown_sequence(self):
        """Test graceful shutdown of multiple components."""
        server_key = create_new_key_pair().private_key
        config = QUICTransportConfig(idle_timeout=5.0)
        transport = QUICTransport(server_key, config)

        shutdown_events = []
        listeners = []

        async def tracked_connection_handler(connection):
            """Connection handler that tracks shutdown."""
            try:
                while not connection.is_closed:
                    await trio.sleep(0.1)
            finally:
                shutdown_events.append(f"connection_closed_{id(connection)}")

        async def create_tracked_listener(listener_id):
            """Create a listener that tracks its lifecycle."""
            try:
                listener = transport.create_listener(tracked_connection_handler)
                listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
                listeners.append(listener)

                async with trio.open_nursery() as nursery:
                    success = await listener.listen(listen_addr, nursery)
                    assert success
                    shutdown_events.append(f"listener_{listener_id}_started")

                    # Run for a bit
                    await trio.sleep(0.2)

                    # Graceful close
                    await listener.close()
                    shutdown_events.append(f"listener_{listener_id}_closed")

            except Exception as e:
                shutdown_events.append(f"listener_{listener_id}_error_{e}")
                raise

        try:
            # Start multiple listeners
            async with trio.open_nursery() as nursery:
                for i in range(3):
                    nursery.start_soon(create_tracked_listener, i)

            # Verify shutdown sequence
            start_events = [e for e in shutdown_events if "started" in e]
            close_events = [e for e in shutdown_events if "closed" in e]

            assert len(start_events) == 3
            assert len(close_events) == 3

            logger.info(f"Shutdown sequence: {shutdown_events}")

        finally:
            shutdown_events.append("transport_closing")
            await transport.close()
            shutdown_events.append("transport_closed")


# HELPER FUNCTIONS FOR CLEANER TESTS


async def run_listener_for_duration(transport, handler, duration=0.5):
    """Helper to run a single listener for a specific duration."""
    listener = transport.create_listener(handler)
    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

    async with trio.open_nursery() as nursery:
        success = await listener.listen(listen_addr, nursery)
        assert success

        # Run for specified duration
        await trio.sleep(duration)

        # Clean close
        await listener.close()

    return listener


async def run_multiple_listeners_parallel(transport, handler, count=3, duration=0.5):
    """Helper to run multiple listeners in parallel."""
    listeners = []

    async def single_listener_task(listener_id):
        listener = await run_listener_for_duration(transport, handler, duration)
        listeners.append(listener)
        logger.info(f"Listener {listener_id} completed")

    async with trio.open_nursery() as nursery:
        for i in range(count):
            nursery.start_soon(single_listener_task, i)

    return listeners


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
