"""
Real integration tests for QUIC Connection ID handling during client-server communication.

This test suite creates actual server and client connections, sends real messages,
and monitors connection IDs throughout the connection lifecycle to ensure proper
connection ID management according to RFC 9000.

Tests cover:
- Initial connection establishment with connection ID extraction
- Connection ID exchange during handshake
- Connection ID usage during message exchange
- Connection ID changes and migration
- Connection ID retirement and cleanup
"""

import time
from typing import Any, Dict, List, Optional

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.transport import QUICTransport, QUICTransportConfig
from libp2p.transport.quic.utils import (
    create_quic_multiaddr,
    quic_multiaddr_to_endpoint,
)


class ConnectionIdTracker:
    """Helper class to track connection IDs during test scenarios."""

    def __init__(self):
        self.server_connection_ids: List[bytes] = []
        self.client_connection_ids: List[bytes] = []
        self.events: List[Dict[str, Any]] = []
        self.server_connection: Optional[QUICConnection] = None
        self.client_connection: Optional[QUICConnection] = None

    def record_event(self, event_type: str, **kwargs):
        """Record a connection ID related event."""
        event = {"timestamp": time.time(), "type": event_type, **kwargs}
        self.events.append(event)
        print(f"📝 CID Event: {event_type} - {kwargs}")

    def capture_server_cids(self, connection: QUICConnection):
        """Capture server-side connection IDs."""
        self.server_connection = connection
        if hasattr(connection._quic, "_peer_cid"):
            cid = connection._quic._peer_cid.cid
            if cid not in self.server_connection_ids:
                self.server_connection_ids.append(cid)
                self.record_event("server_peer_cid_captured", cid=cid.hex())

        if hasattr(connection._quic, "_host_cids"):
            for host_cid in connection._quic._host_cids:
                if host_cid.cid not in self.server_connection_ids:
                    self.server_connection_ids.append(host_cid.cid)
                    self.record_event(
                        "server_host_cid_captured",
                        cid=host_cid.cid.hex(),
                        sequence=host_cid.sequence_number,
                    )

    def capture_client_cids(self, connection: QUICConnection):
        """Capture client-side connection IDs."""
        self.client_connection = connection
        if hasattr(connection._quic, "_peer_cid"):
            cid = connection._quic._peer_cid.cid
            if cid not in self.client_connection_ids:
                self.client_connection_ids.append(cid)
                self.record_event("client_peer_cid_captured", cid=cid.hex())

        if hasattr(connection._quic, "_peer_cid_available"):
            for peer_cid in connection._quic._peer_cid_available:
                if peer_cid.cid not in self.client_connection_ids:
                    self.client_connection_ids.append(peer_cid.cid)
                    self.record_event(
                        "client_available_cid_captured",
                        cid=peer_cid.cid.hex(),
                        sequence=peer_cid.sequence_number,
                    )

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of captured connection IDs and events."""
        return {
            "server_cids": [cid.hex() for cid in self.server_connection_ids],
            "client_cids": [cid.hex() for cid in self.client_connection_ids],
            "total_events": len(self.events),
            "events": self.events,
        }


class TestRealConnectionIdHandling:
    """Integration tests for real QUIC connection ID handling."""

    @pytest.fixture
    def server_config(self):
        """Server transport configuration."""
        return QUICTransportConfig(
            idle_timeout=10.0,
            connection_timeout=5.0,
            max_concurrent_streams=100,
        )

    @pytest.fixture
    def client_config(self):
        """Client transport configuration."""
        return QUICTransportConfig(
            idle_timeout=10.0,
            connection_timeout=5.0,
        )

    @pytest.fixture
    def server_key(self):
        """Generate server private key."""
        return create_new_key_pair().private_key

    @pytest.fixture
    def client_key(self):
        """Generate client private key."""
        return create_new_key_pair().private_key

    @pytest.fixture
    def cid_tracker(self):
        """Create connection ID tracker."""
        return ConnectionIdTracker()

    # Test 1: Basic Connection Establishment with Connection ID Tracking
    @pytest.mark.trio
    async def test_connection_establishment_cid_tracking(
        self, server_key, client_key, server_config, client_config, cid_tracker
    ):
        """Test basic connection establishment while tracking connection IDs."""
        print("\n🔬 Testing connection establishment with CID tracking...")

        # Create server transport
        server_transport = QUICTransport(server_key, server_config)
        server_connections = []

        async def server_handler(connection: QUICConnection):
            """Handle incoming connections and track CIDs."""
            print(f"✅ Server: New connection from {connection.remote_peer_id()}")
            server_connections.append(connection)

            # Capture server-side connection IDs
            cid_tracker.capture_server_cids(connection)
            cid_tracker.record_event("server_connection_established")

            # Wait for potential messages
            try:
                async with trio.open_nursery() as nursery:
                    # Accept and handle streams
                    async def handle_streams():
                        while not connection.is_closed:
                            try:
                                stream = await connection.accept_stream(timeout=1.0)
                                nursery.start_soon(handle_stream, stream)
                            except Exception:
                                break

                    async def handle_stream(stream):
                        """Handle individual stream."""
                        data = await stream.read(1024)
                        print(f"📨 Server received: {data}")
                        await stream.write(b"Server response: " + data)
                        await stream.close_write()

                    nursery.start_soon(handle_streams)
                    await trio.sleep(2.0)  # Give time for communication
                    nursery.cancel_scope.cancel()

            except Exception as e:
                print(f"⚠️ Server handler error: {e}")

        # Create and start server listener
        listener = server_transport.create_listener(server_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")  # Random port

        async with trio.open_nursery() as server_nursery:
            try:
                # Start server
                success = await listener.listen(listen_addr, server_nursery)
                assert success, "Server failed to start"

                # Get actual server address
                server_addrs = listener.get_addrs()
                assert len(server_addrs) == 1
                server_addr = server_addrs[0]

                host, port = quic_multiaddr_to_endpoint(server_addr)
                print(f"🌐 Server listening on {host}:{port}")

                cid_tracker.record_event("server_started", host=host, port=port)

                # Create client and connect
                client_transport = QUICTransport(client_key, client_config)

                try:
                    print(f"🔗 Client connecting to {server_addr}")
                    connection = await client_transport.dial(server_addr)
                    assert connection is not None, "Failed to establish connection"

                    # Capture client-side connection IDs
                    cid_tracker.capture_client_cids(connection)
                    cid_tracker.record_event("client_connection_established")

                    print("✅ Connection established successfully!")

                    # Test message exchange with CID monitoring
                    await self.test_message_exchange_with_cid_monitoring(
                        connection, cid_tracker
                    )

                    # Test connection ID changes
                    await self.test_connection_id_changes(connection, cid_tracker)

                    # Close connection
                    await connection.close()
                    cid_tracker.record_event("client_connection_closed")

                finally:
                    await client_transport.close()

                # Wait a bit for server to process
                await trio.sleep(0.5)

                # Verify connection IDs were tracked
                summary = cid_tracker.get_summary()
                print(f"\n📊 Connection ID Summary:")
                print(f"  Server CIDs: {len(summary['server_cids'])}")
                print(f"  Client CIDs: {len(summary['client_cids'])}")
                print(f"  Total events: {summary['total_events']}")

                # Assertions
                assert len(server_connections) == 1, (
                    "Should have exactly one server connection"
                )
                assert len(summary["server_cids"]) > 0, (
                    "Should have captured server connection IDs"
                )
                assert len(summary["client_cids"]) > 0, (
                    "Should have captured client connection IDs"
                )
                assert summary["total_events"] >= 4, "Should have multiple CID events"

                server_nursery.cancel_scope.cancel()

            finally:
                await listener.close()
                await server_transport.close()

    async def test_message_exchange_with_cid_monitoring(
        self, connection: QUICConnection, cid_tracker: ConnectionIdTracker
    ):
        """Test message exchange while monitoring connection ID usage."""

        print("\n📤 Testing message exchange with CID monitoring...")

        try:
            # Capture CIDs before sending messages
            initial_client_cids = len(cid_tracker.client_connection_ids)
            cid_tracker.capture_client_cids(connection)
            cid_tracker.record_event("pre_message_cid_capture")

            # Send a message
            stream = await connection.open_stream()
            test_message = b"Hello from client with CID tracking!"

            print(f"📤 Sending: {test_message}")
            await stream.write(test_message)
            await stream.close_write()

            cid_tracker.record_event("message_sent", size=len(test_message))

            # Read response
            response = await stream.read(1024)
            print(f"📥 Received: {response}")

            cid_tracker.record_event("response_received", size=len(response))

            # Capture CIDs after message exchange
            cid_tracker.capture_client_cids(connection)
            final_client_cids = len(cid_tracker.client_connection_ids)

            cid_tracker.record_event(
                "post_message_cid_capture",
                cid_count_change=final_client_cids - initial_client_cids,
            )

            # Verify message was exchanged successfully
            assert b"Server response:" in response
            assert test_message in response

        except Exception as e:
            cid_tracker.record_event("message_exchange_error", error=str(e))
            raise

    async def test_connection_id_changes(
        self, connection: QUICConnection, cid_tracker: ConnectionIdTracker
    ):
        """Test connection ID changes during active connection."""

        print("\n🔄 Testing connection ID changes...")

        try:
            # Get initial connection ID state
            initial_peer_cid = None
            if hasattr(connection._quic, "_peer_cid"):
                initial_peer_cid = connection._quic._peer_cid.cid
                cid_tracker.record_event("initial_peer_cid", cid=initial_peer_cid.hex())

            # Check available connection IDs
            available_cids = []
            if hasattr(connection._quic, "_peer_cid_available"):
                available_cids = connection._quic._peer_cid_available[:]
                cid_tracker.record_event(
                    "available_cids_count", count=len(available_cids)
                )

            # Try to change connection ID if alternatives are available
            if available_cids:
                print(
                    f"🔄 Attempting connection ID change (have {len(available_cids)} alternatives)"
                )

                try:
                    connection._quic.change_connection_id()
                    cid_tracker.record_event("connection_id_change_attempted")

                    # Capture new state
                    new_peer_cid = None
                    if hasattr(connection._quic, "_peer_cid"):
                        new_peer_cid = connection._quic._peer_cid.cid
                        cid_tracker.record_event("new_peer_cid", cid=new_peer_cid.hex())

                    # Verify change occurred
                    if initial_peer_cid and new_peer_cid:
                        if initial_peer_cid != new_peer_cid:
                            print("✅ Connection ID successfully changed!")
                            cid_tracker.record_event("connection_id_change_success")
                        else:
                            print("ℹ️ Connection ID remained the same")
                            cid_tracker.record_event("connection_id_change_no_change")

                except Exception as e:
                    print(f"⚠️ Connection ID change failed: {e}")
                    cid_tracker.record_event(
                        "connection_id_change_failed", error=str(e)
                    )
            else:
                print("ℹ️ No alternative connection IDs available for change")
                cid_tracker.record_event("no_alternative_cids_available")

        except Exception as e:
            cid_tracker.record_event("connection_id_change_test_error", error=str(e))
            print(f"⚠️ Connection ID change test error: {e}")

    # Test 2: Multiple Connection CID Isolation
    @pytest.mark.trio
    async def test_multiple_connections_cid_isolation(
        self, server_key, client_key, server_config, client_config
    ):
        """Test that multiple connections have isolated connection IDs."""

        print("\n🔬 Testing multiple connections CID isolation...")

        # Track connection IDs for multiple connections
        connection_trackers: Dict[str, ConnectionIdTracker] = {}
        server_connections = []

        async def server_handler(connection: QUICConnection):
            """Handle connections and track their CIDs separately."""
            connection_id = f"conn_{len(server_connections)}"
            server_connections.append(connection)

            tracker = ConnectionIdTracker()
            connection_trackers[connection_id] = tracker

            tracker.capture_server_cids(connection)
            tracker.record_event(
                "server_connection_established", connection_id=connection_id
            )

            print(f"✅ Server: Connection {connection_id} established")

            # Simple echo server
            try:
                stream = await connection.accept_stream(timeout=2.0)
                data = await stream.read(1024)
                await stream.write(f"Response from {connection_id}: ".encode() + data)
                await stream.close_write()
                tracker.record_event("message_handled", connection_id=connection_id)
            except Exception:
                pass  # Timeout is expected

        # Create server
        server_transport = QUICTransport(server_key, server_config)
        listener = server_transport.create_listener(server_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        async with trio.open_nursery() as nursery:
            try:
                # Start server
                success = await listener.listen(listen_addr, nursery)
                assert success

                server_addr = listener.get_addrs()[0]
                host, port = quic_multiaddr_to_endpoint(server_addr)
                print(f"🌐 Server listening on {host}:{port}")

                # Create multiple client connections
                num_connections = 3
                client_trackers = []

                for i in range(num_connections):
                    print(f"\n🔗 Creating client connection {i + 1}/{num_connections}")

                    client_transport = QUICTransport(client_key, client_config)
                    try:
                        connection = await client_transport.dial(server_addr)

                        # Track this client's connection IDs
                        tracker = ConnectionIdTracker()
                        client_trackers.append(tracker)
                        tracker.capture_client_cids(connection)
                        tracker.record_event(
                            "client_connection_established", client_num=i
                        )

                        # Send a unique message
                        stream = await connection.open_stream()
                        message = f"Message from client {i}".encode()
                        await stream.write(message)
                        await stream.close_write()

                        response = await stream.read(1024)
                        print(f"📥 Client {i} received: {response.decode()}")
                        tracker.record_event("message_exchanged", client_num=i)

                        await connection.close()
                        tracker.record_event("client_connection_closed", client_num=i)

                    finally:
                        await client_transport.close()

                # Wait for server to process all connections
                await trio.sleep(1.0)

                # Analyze connection ID isolation
                print(
                    f"\n📊 Analyzing CID isolation across {num_connections} connections:"
                )

                all_server_cids = set()
                all_client_cids = set()

                # Collect all connection IDs
                for conn_id, tracker in connection_trackers.items():
                    summary = tracker.get_summary()
                    server_cids = set(summary["server_cids"])
                    all_server_cids.update(server_cids)
                    print(f"  {conn_id}: {len(server_cids)} server CIDs")

                for i, tracker in enumerate(client_trackers):
                    summary = tracker.get_summary()
                    client_cids = set(summary["client_cids"])
                    all_client_cids.update(client_cids)
                    print(f"  client_{i}: {len(client_cids)} client CIDs")

                # Verify isolation
                print(f"\nTotal unique server CIDs: {len(all_server_cids)}")
                print(f"Total unique client CIDs: {len(all_client_cids)}")

                # Assertions
                assert len(server_connections) == num_connections, (
                    f"Expected {num_connections} server connections"
                )
                assert len(connection_trackers) == num_connections, (
                    "Should have trackers for all server connections"
                )
                assert len(client_trackers) == num_connections, (
                    "Should have trackers for all client connections"
                )

                # Each connection should have unique connection IDs
                assert len(all_server_cids) >= num_connections, (
                    "Server connections should have unique CIDs"
                )
                assert len(all_client_cids) >= num_connections, (
                    "Client connections should have unique CIDs"
                )

                print("✅ Connection ID isolation verified!")

                nursery.cancel_scope.cancel()

            finally:
                await listener.close()
                await server_transport.close()

    # Test 3: Connection ID Persistence During Migration
    @pytest.mark.trio
    async def test_connection_id_during_migration(
        self, server_key, client_key, server_config, client_config, cid_tracker
    ):
        """Test connection ID behavior during connection migration scenarios."""

        print("\n🔬 Testing connection ID during migration...")

        # Create server
        server_transport = QUICTransport(server_key, server_config)
        server_connection_ref = []

        async def migration_server_handler(connection: QUICConnection):
            """Server handler that tracks connection migration."""
            server_connection_ref.append(connection)
            cid_tracker.capture_server_cids(connection)
            cid_tracker.record_event("migration_server_connection_established")

            print("✅ Migration server: Connection established")

            # Handle multiple message exchanges to observe CID behavior
            message_count = 0
            try:
                while message_count < 3 and not connection.is_closed:
                    try:
                        stream = await connection.accept_stream(timeout=2.0)
                        data = await stream.read(1024)
                        message_count += 1

                        # Capture CIDs after each message
                        cid_tracker.capture_server_cids(connection)
                        cid_tracker.record_event(
                            "migration_server_message_received",
                            message_num=message_count,
                            data_size=len(data),
                        )

                        response = (
                            f"Migration response {message_count}: ".encode() + data
                        )
                        await stream.write(response)
                        await stream.close_write()

                        print(f"📨 Migration server handled message {message_count}")

                    except Exception as e:
                        print(f"⚠️ Migration server stream error: {e}")
                        break

            except Exception as e:
                print(f"⚠️ Migration server handler error: {e}")

        # Start server
        listener = server_transport.create_listener(migration_server_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        async with trio.open_nursery() as nursery:
            try:
                success = await listener.listen(listen_addr, nursery)
                assert success

                server_addr = listener.get_addrs()[0]
                host, port = quic_multiaddr_to_endpoint(server_addr)
                print(f"🌐 Migration server listening on {host}:{port}")

                # Create client connection
                client_transport = QUICTransport(client_key, client_config)

                try:
                    connection = await client_transport.dial(server_addr)
                    cid_tracker.capture_client_cids(connection)
                    cid_tracker.record_event("migration_client_connection_established")

                    # Send multiple messages with potential CID changes between them
                    for msg_num in range(3):
                        print(f"\n📤 Sending migration test message {msg_num + 1}")

                        # Capture CIDs before message
                        cid_tracker.capture_client_cids(connection)
                        cid_tracker.record_event(
                            "migration_pre_message_cid_capture", message_num=msg_num + 1
                        )

                        # Send message
                        stream = await connection.open_stream()
                        message = f"Migration test message {msg_num + 1}".encode()
                        await stream.write(message)
                        await stream.close_write()

                        # Try to change connection ID between messages (if possible)
                        if msg_num == 1:  # Change CID after first message
                            try:
                                if (
                                    hasattr(
                                        connection._quic,
                                        "_peer_cid_available",
                                    )
                                    and connection._quic._peer_cid_available
                                ):
                                    print(
                                        "🔄 Attempting connection ID change for migration test"
                                    )
                                    connection._quic.change_connection_id()
                                    cid_tracker.record_event(
                                        "migration_cid_change_attempted",
                                        message_num=msg_num + 1,
                                    )
                            except Exception as e:
                                print(f"⚠️ CID change failed: {e}")
                                cid_tracker.record_event(
                                    "migration_cid_change_failed", error=str(e)
                                )

                        # Read response
                        response = await stream.read(1024)
                        print(f"📥 Received migration response: {response.decode()}")

                        # Capture CIDs after message
                        cid_tracker.capture_client_cids(connection)
                        cid_tracker.record_event(
                            "migration_post_message_cid_capture",
                            message_num=msg_num + 1,
                        )

                        # Small delay between messages
                        await trio.sleep(0.1)

                    await connection.close()
                    cid_tracker.record_event("migration_client_connection_closed")

                finally:
                    await client_transport.close()

                # Wait for server processing
                await trio.sleep(0.5)

                # Analyze migration behavior
                summary = cid_tracker.get_summary()
                print(f"\n📊 Migration Test Summary:")
                print(f"  Total CID events: {summary['total_events']}")
                print(f"  Unique server CIDs: {len(set(summary['server_cids']))}")
                print(f"  Unique client CIDs: {len(set(summary['client_cids']))}")

                # Print event timeline
                print(f"\n📋 Event Timeline:")
                for event in summary["events"][-10:]:  # Last 10 events
                    print(f"  {event['type']}: {event.get('message_num', 'N/A')}")

                # Assertions
                assert len(server_connection_ref) == 1, (
                    "Should have one server connection"
                )
                assert summary["total_events"] >= 6, (
                    "Should have multiple migration events"
                )

                print("✅ Migration test completed!")

                nursery.cancel_scope.cancel()

            finally:
                await listener.close()
                await server_transport.close()

    # Test 4: Connection ID State Validation
    @pytest.mark.trio
    async def test_connection_id_state_validation(
        self, server_key, client_key, server_config, client_config, cid_tracker
    ):
        """Test validation of connection ID state throughout connection lifecycle."""

        print("\n🔬 Testing connection ID state validation...")

        # Create server with detailed CID state tracking
        server_transport = QUICTransport(server_key, server_config)
        connection_states = []

        async def state_tracking_handler(connection: QUICConnection):
            """Track detailed connection ID state."""

            def capture_detailed_state(stage: str):
                """Capture detailed connection ID state."""
                state = {
                    "stage": stage,
                    "timestamp": time.time(),
                }

                # Capture aioquic connection state
                quic_conn = connection._quic
                if hasattr(quic_conn, "_peer_cid"):
                    state["current_peer_cid"] = quic_conn._peer_cid.cid.hex()
                    state["current_peer_cid_sequence"] = quic_conn._peer_cid.sequence_number

                if quic_conn._peer_cid_available:
                    state["available_peer_cids"] = [
                        {"cid": cid.cid.hex(), "sequence": cid.sequence_number}
                        for cid in quic_conn._peer_cid_available
                    ]

                if quic_conn._host_cids:
                    state["host_cids"] = [
                        {
                            "cid": cid.cid.hex(),
                            "sequence": cid.sequence_number,
                            "was_sent": getattr(cid, "was_sent", False),
                        }
                        for cid in quic_conn._host_cids
                    ]

                if hasattr(quic_conn, "_peer_cid_sequence_numbers"):
                    state["tracked_sequences"] = list(
                        quic_conn._peer_cid_sequence_numbers
                    )

                if hasattr(quic_conn, "_peer_retire_prior_to"):
                    state["retire_prior_to"] = quic_conn._peer_retire_prior_to

                connection_states.append(state)
                cid_tracker.record_event("detailed_state_captured", stage=stage)

                print(f"📋 State at {stage}:")
                print(f"  Current peer CID: {state.get('current_peer_cid', 'None')}")
                print(f"  Available CIDs: {len(state.get('available_peer_cids', []))}")
                print(f"  Host CIDs: {len(state.get('host_cids', []))}")

            # Initial state
            capture_detailed_state("connection_established")

            # Handle stream and capture state changes
            try:
                stream = await connection.accept_stream(timeout=3.0)
                capture_detailed_state("stream_accepted")

                data = await stream.read(1024)
                capture_detailed_state("data_received")

                await stream.write(b"State validation response: " + data)
                await stream.close_write()
                capture_detailed_state("response_sent")

            except Exception as e:
                print(f"⚠️ State tracking handler error: {e}")
                capture_detailed_state("error_occurred")

        # Start server
        listener = server_transport.create_listener(state_tracking_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        async with trio.open_nursery() as nursery:
            try:
                success = await listener.listen(listen_addr, nursery)
                assert success

                server_addr = listener.get_addrs()[0]
                host, port = quic_multiaddr_to_endpoint(server_addr)
                print(f"🌐 State validation server listening on {host}:{port}")

                # Create client and test state validation
                client_transport = QUICTransport(client_key, client_config)

                try:
                    connection = await client_transport.dial(server_addr)
                    cid_tracker.record_event("state_validation_client_connected")

                    # Send test message
                    stream = await connection.open_stream()
                    test_message = b"State validation test message"
                    await stream.write(test_message)
                    await stream.close_write()

                    response = await stream.read(1024)
                    print(f"📥 State validation response: {response}")

                    await connection.close()
                    cid_tracker.record_event("state_validation_connection_closed")

                finally:
                    await client_transport.close()

                # Wait for server state capture
                await trio.sleep(1.0)

                # Analyze captured states
                print(f"\n📊 Connection ID State Analysis:")
                print(f"  Total state snapshots: {len(connection_states)}")

                for i, state in enumerate(connection_states):
                    stage = state["stage"]
                    print(f"\n  State {i + 1}: {stage}")
                    print(f"    Current CID: {state.get('current_peer_cid', 'None')}")
                    print(
                        f"    Available CIDs: {len(state.get('available_peer_cids', []))}"
                    )
                    print(f"    Host CIDs: {len(state.get('host_cids', []))}")
                    print(
                        f"    Tracked sequences: {state.get('tracked_sequences', [])}"
                    )

                # Validate state consistency
                assert len(connection_states) >= 3, (
                    "Should have captured multiple states"
                )

                # Check that connection ID state is consistent
                for state in connection_states:
                    # Should always have a current peer CID
                    assert "current_peer_cid" in state, (
                        f"Missing current_peer_cid in {state['stage']}"
                    )

                    # Host CIDs should be present for server
                    if "host_cids" in state:
                        assert isinstance(state["host_cids"], list), (
                            "Host CIDs should be a list"
                        )

                print("✅ Connection ID state validation completed!")

                nursery.cancel_scope.cancel()

            finally:
                await listener.close()
                await server_transport.close()

    # Test 5: Performance Impact of Connection ID Operations
    @pytest.mark.trio
    async def test_connection_id_performance_impact(
        self, server_key, client_key, server_config, client_config
    ):
        """Test performance impact of connection ID operations."""

        print("\n🔬 Testing connection ID performance impact...")

        # Performance tracking
        performance_data = {
            "connection_times": [],
            "message_times": [],
            "cid_change_times": [],
            "total_messages": 0,
        }

        async def performance_server_handler(connection: QUICConnection):
            """High-performance server handler."""
            message_count = 0
            start_time = time.time()

            try:
                while message_count < 10:  # Handle 10 messages quickly
                    try:
                        stream = await connection.accept_stream(timeout=1.0)
                        message_start = time.time()

                        data = await stream.read(1024)
                        await stream.write(b"Fast response: " + data)
                        await stream.close_write()

                        message_time = time.time() - message_start
                        performance_data["message_times"].append(message_time)
                        message_count += 1

                    except Exception:
                        break

                total_time = time.time() - start_time
                performance_data["total_messages"] = message_count
                print(
                    f"⚡ Server handled {message_count} messages in {total_time:.3f}s"
                )

            except Exception as e:
                print(f"⚠️ Performance server error: {e}")

        # Create high-performance server
        server_transport = QUICTransport(server_key, server_config)
        listener = server_transport.create_listener(performance_server_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        async with trio.open_nursery() as nursery:
            try:
                success = await listener.listen(listen_addr, nursery)
                assert success

                server_addr = listener.get_addrs()[0]
                host, port = quic_multiaddr_to_endpoint(server_addr)
                print(f"🌐 Performance server listening on {host}:{port}")

                # Test connection establishment time
                client_transport = QUICTransport(client_key, client_config)

                try:
                    connection_start = time.time()
                    connection = await client_transport.dial(server_addr)
                    connection_time = time.time() - connection_start
                    performance_data["connection_times"].append(connection_time)

                    print(f"⚡ Connection established in {connection_time:.3f}s")

                    # Send multiple messages rapidly
                    for i in range(10):
                        stream = await connection.open_stream()
                        message = f"Performance test message {i}".encode()

                        message_start = time.time()
                        await stream.write(message)
                        await stream.close_write()

                        response = await stream.read(1024)
                        message_time = time.time() - message_start

                        print(f"📤 Message {i + 1} round-trip: {message_time:.3f}s")

                        # Try connection ID change on message 5
                        if i == 4:
                            try:
                                cid_change_start = time.time()
                                if (
                                    hasattr(
                                        connection._quic,
                                        "_peer_cid_available",
                                    )
                                    and connection._quic._peer_cid_available
                                ):
                                    connection._quic.change_connection_id()
                                    cid_change_time = time.time() - cid_change_start
                                    performance_data["cid_change_times"].append(
                                        cid_change_time
                                    )
                                    print(f"🔄 CID change took {cid_change_time:.3f}s")
                            except Exception as e:
                                print(f"⚠️ CID change failed: {e}")

                    await connection.close()

                finally:
                    await client_transport.close()

                # Wait for server completion
                await trio.sleep(0.5)

                # Analyze performance data
                print(f"\n📊 Performance Analysis:")
                if performance_data["connection_times"]:
                    avg_connection = sum(performance_data["connection_times"]) / len(
                        performance_data["connection_times"]
                    )
                    print(f"  Average connection time: {avg_connection:.3f}s")

                if performance_data["message_times"]:
                    avg_message = sum(performance_data["message_times"]) / len(
                        performance_data["message_times"]
                    )
                    print(f"  Average message time: {avg_message:.3f}s")
                    print(f"  Total messages: {performance_data['total_messages']}")

                if performance_data["cid_change_times"]:
                    avg_cid_change = sum(performance_data["cid_change_times"]) / len(
                        performance_data["cid_change_times"]
                    )
                    print(f"  Average CID change time: {avg_cid_change:.3f}s")

                # Performance assertions
                if performance_data["connection_times"]:
                    assert avg_connection < 2.0, (
                        "Connection should establish within 2 seconds"
                    )

                if performance_data["message_times"]:
                    assert avg_message < 0.5, (
                        "Messages should complete within 0.5 seconds"
                    )

                print("✅ Performance test completed!")

                nursery.cancel_scope.cancel()

            finally:
                await listener.close()
                await server_transport.close()
