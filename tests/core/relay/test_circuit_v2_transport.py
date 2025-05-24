"""Tests for the Circuit Relay v2 transport functionality."""

import logging
import pytest
import trio

from libp2p.network.stream.exceptions import (
    StreamEOF,
    StreamError,
    StreamReset,
)
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.protocol import (
    DEFAULT_RELAY_LIMITS,
    PROTOCOL_ID,
    STOP_PROTOCOL_ID,
    CircuitV2Protocol,
)
from libp2p.relay.circuit_v2.transport import (
    CircuitV2Transport,
)
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.pb import circuit_pb2 as proto
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.constants import MAX_READ_LEN
from libp2p.tools.utils import connect
from tests.utils.factories import HostFactory

logger = logging.getLogger(__name__)

# Test timeouts
CONNECT_TIMEOUT = 15  # seconds
STREAM_TIMEOUT = 15  # seconds
HANDLER_TIMEOUT = 15  # seconds
SLEEP_TIME = 1.0  # seconds
RELAY_TIMEOUT = 20  # seconds

# Message for testing
TEST_MESSAGE = b"Hello, Circuit Relay!"
TEST_RESPONSE = b"Hello from the other side!"

# Stream handler for testing
async def echo_stream_handler(stream):
    """Simple echo handler that responds to messages."""
    logger.info("Echo handler received stream")
    try:
        while True:
            data = await stream.read(MAX_READ_LEN)
            if not data:
                logger.info("Stream closed by remote")
                break
            
            logger.info("Received data: %s", data)
            await stream.write(TEST_RESPONSE)
            logger.info("Sent response")
    except (StreamEOF, StreamReset) as e:
        logger.info("Stream ended: %s", str(e))
    except Exception as e:
        logger.error("Error in echo handler: %s", str(e))
    finally:
        await stream.close()

@pytest.mark.trio
async def test_circuit_v2_transport_initialization():
    """Test that the Circuit v2 transport initializes correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        transport = CircuitV2Transport(host)
        
        # Verify transport properties
        assert transport.host == host, "Host not set correctly"
        assert hasattr(transport, "relays"), "Transport should track relays"
        assert len(transport.relays) == 0, "Should start with no relays"

@pytest.mark.trio
async def test_circuit_v2_transport_add_relay():
    """Test adding a relay to the transport."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host, relay_host = hosts
        transport = CircuitV2Transport(host)
        
        # Add relay to transport
        transport.add_relay(relay_host.get_id())
        
        # Verify relay was added
        assert len(transport.relays) == 1, "Should have one relay"
        assert relay_host.get_id() in transport.relays, "Relay should be in transport's relay list"

@pytest.mark.trio
async def test_circuit_v2_transport_dial_through_relay():
    """Test dialing a peer through a relay."""
    async with HostFactory.create_batch_and_listen(3) as hosts:
        client_host, relay_host, target_host = hosts
        logger.info("Created hosts for test_circuit_v2_transport_dial_through_relay")
        logger.info("Client host ID: %s", client_host.get_id())
        logger.info("Relay host ID: %s", relay_host.get_id())
        logger.info("Target host ID: %s", target_host.get_id())
        
        # Setup relay with Circuit v2 protocol
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )
        relay_protocol = CircuitV2Protocol(relay_host, limits, allow_hop=True)
        
        # Register test handler on target
        test_protocol = "/test/echo/1.0.0"
        target_host.set_stream_handler(test_protocol, echo_stream_handler)
        
        # Setup transport on client
        client_transport = CircuitV2Transport(client_host)
        client_transport.add_relay(relay_host.get_id())
        
        # Connect client to relay and relay to target
        try:
            with trio.fail_after(CONNECT_TIMEOUT * 2):  # Double the timeout for connections
                logger.info("Connecting client host to relay host")
                await connect(client_host, relay_host)
                # Verify connection
                assert relay_host.get_id() in client_host.get_network().connections, "Client not connected to relay"
                assert client_host.get_id() in relay_host.get_network().connections, "Relay not connected to client"
                logger.info("Client-Relay connection verified")
                
                # Wait to ensure connection is fully established
                await trio.sleep(SLEEP_TIME)
                
                logger.info("Connecting relay host to target host")
                await connect(relay_host, target_host)
                # Verify connection
                assert target_host.get_id() in relay_host.get_network().connections, "Relay not connected to target"
                assert relay_host.get_id() in target_host.get_network().connections, "Target not connected to relay"
                logger.info("Relay-Target connection verified")
                
                # Wait to ensure connection is fully established
                await trio.sleep(SLEEP_TIME)
                
                logger.info("All connections established and verified")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise
        
        # Start relay protocol
        async with background_trio_service(relay_protocol):
            await relay_protocol.event_started.wait()
            logger.info("Relay protocol service started")
            
            # Wait for relay protocol to fully initialize
            await trio.sleep(SLEEP_TIME * 2)
            
            # Make a reservation
            reservation_stream = None
            try:
                with trio.fail_after(RELAY_TIMEOUT * 2):  # Double the timeout for reservation
                    logger.info("Making reservation with relay")
                    reservation_stream = await client_host.new_stream(relay_host.get_id(), [PROTOCOL_ID])
                    logger.info("Stream opened for reservation")
                    
                    # Send reservation request
                    request = proto.HopMessage(
                        type=proto.HopMessage.RESERVE,
                        peer=client_host.get_id().to_bytes()
                    )
                    logger.info("Sending reservation request")
                    await reservation_stream.write(request.SerializeToString())
                    logger.info("Reservation request sent")
                    
                    # Wait for response to be processed
                    await trio.sleep(SLEEP_TIME)
                    
                    # Read response
                    logger.info("Reading reservation response")
                    response_bytes = await reservation_stream.read(MAX_READ_LEN)
                    if not response_bytes:
                        logger.error("Empty response received for reservation")
                        raise Exception("Empty reservation response")
                        
                    response = proto.HopMessage()
                    response.ParseFromString(response_bytes)
                    
                    # Log response details
                    logger.info("Received reservation response: type=%s, status=%s", 
                               response.type,
                               response.status.code if response.HasField("status") else "No status")
                    
                    # Verify reservation response
                    assert response.type == proto.HopMessage.RESERVE, f"Wrong response type: {response.type}"
                    assert response.HasField("status"), "No status field in response"
                    assert response.status.code == proto.Status.OK, f"Reservation failed: {response.status.message if response.HasField('status') else 'Unknown error'}"
                    logger.info("Reservation successful")
                    
                    # Close reservation stream
                    await reservation_stream.close()
                    reservation_stream = None
                    logger.info("Reservation stream closed")
                    
                    # Wait for reservation to be fully processed
                    await trio.sleep(SLEEP_TIME * 2)
            except Exception as e:
                logger.error("Failed to make reservation: %s", str(e))
                raise
            finally:
                if reservation_stream:
                    try:
                        await reservation_stream.close()
                    except Exception:
                        pass
            
            # Try to dial the target through the relay
            relay_stream = None
            try:
                with trio.fail_after(RELAY_TIMEOUT * 2):  # Double the timeout for relay dialing
                    logger.info("Dialing target through relay")
                    relay_conn = await client_transport.dial_peer(target_host.get_id())
                    assert relay_conn is not None, "Failed to establish relay connection"
                    logger.info("Relay connection established")
                    
                    # Wait for relay connection to be fully established
                    await trio.sleep(SLEEP_TIME * 2)
                    
                    # Verify connection state
                    assert client_host.is_peer_connected(target_host.get_id()), "Target not in client's connections after relay dial"
                    logger.info("Connection verified in client's connection list")
                    
                    # Try to open a stream over the relay connection
                    logger.info("Opening stream over relay connection")
                    relay_stream = await client_host.new_stream(target_host.get_id(), [test_protocol])
                    assert relay_stream is not None, "Failed to open stream over relay"
                    logger.info("Stream opened over relay connection")
                    
                    # Wait to ensure stream is fully established
                    await trio.sleep(SLEEP_TIME)
                    
                    # Send test message
                    logger.info("Sending test message: %s", TEST_MESSAGE)
                    await relay_stream.write(TEST_MESSAGE)
                    logger.info("Test message sent")
                    
                    # Wait for message to be processed
                    await trio.sleep(SLEEP_TIME)
                    
                    # Receive response
                    logger.info("Waiting for response")
                    response = await relay_stream.read(MAX_READ_LEN)
                    if not response:
                        logger.error("Empty response received")
                        raise Exception("Empty response")
                        
                    logger.info("Received response: %s", response)
                    assert response == TEST_RESPONSE, f"Wrong response: expected {TEST_RESPONSE}, got {response}"
                    
                    # Success!
                    logger.info("Relay test successful!")
            except Exception as e:
                logger.error("Failed relay test: %s", str(e))
                
                # Diagnostic information
                logger.error("Client connections: %s", list(client_host.get_network().connections.keys()))
                logger.error("Relay connections: %s", list(relay_host.get_network().connections.keys()))
                logger.error("Target connections: %s", list(target_host.get_network().connections.keys()))
                
                raise
            finally:
                if relay_stream:
                    try:
                        await relay_stream.close()
                    except Exception:
                        pass

@pytest.mark.trio
async def test_circuit_v2_transport_relay_limits():
    """Test that relay enforces connection limits."""
    async with HostFactory.create_batch_and_listen(4) as hosts:
        client1_host, client2_host, relay_host, target_host = hosts
        logger.info("Created hosts for test_circuit_v2_transport_relay_limits")
        
        # Setup relay with strict limits
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=1,  # Only allow one circuit
            max_reservations=2,    # Allow both clients to reserve
        )
        relay_protocol = CircuitV2Protocol(relay_host, limits, allow_hop=True)
        
        # Register test handler on target
        test_protocol = "/test/echo/1.0.0"
        target_host.set_stream_handler(test_protocol, echo_stream_handler)
        
        # Setup transports on clients
        client1_transport = CircuitV2Transport(client1_host)
        client1_transport.add_relay(relay_host.get_id())
        
        client2_transport = CircuitV2Transport(client2_host)
        client2_transport.add_relay(relay_host.get_id())
        
        # Connect all peers
        try:
            with trio.fail_after(CONNECT_TIMEOUT):
                # Connect clients to relay
                await connect(client1_host, relay_host)
                await connect(client2_host, relay_host)
                
                # Connect relay to target
                await connect(relay_host, target_host)
                
                logger.info("All connections established")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise
        
        # Start relay protocol
        async with background_trio_service(relay_protocol):
            await relay_protocol.event_started.wait()
            logger.info("Relay protocol service started")
            
            # Make reservations for both clients
            for i, client_host in enumerate([client1_host, client2_host], 1):
                try:
                    with trio.fail_after(RELAY_TIMEOUT):
                        logger.info(f"Making reservation for client {i}")
                        reservation_stream = await client_host.new_stream(relay_host.get_id(), [PROTOCOL_ID])
                        
                        # Send reservation request
                        request = proto.HopMessage(
                            type=proto.HopMessage.RESERVE,
                            peer=client_host.get_id().to_bytes()
                        )
                        await reservation_stream.write(request.SerializeToString())
                        
                        # Read response
                        response_bytes = await reservation_stream.read(MAX_READ_LEN)
                        response = proto.HopMessage()
                        response.ParseFromString(response_bytes)
                        
                        # Verify reservation response
                        assert response.type == proto.HopMessage.RESERVE, "Wrong response type"
                        assert response.status.code == proto.Status.OK, f"Reservation failed for client {i}"
                        logger.info(f"Reservation successful for client {i}")
                        
                        # Close reservation stream
                        await reservation_stream.close()
                except Exception as e:
                    logger.error(f"Failed to make reservation for client {i}: {str(e)}")
                    raise
            
            # First client connects through relay (should succeed)
            relay_conn1 = None
            try:
                with trio.fail_after(RELAY_TIMEOUT):
                    logger.info("Client 1 dialing target through relay")
                    relay_conn1 = await client1_transport.dial_peer(target_host.get_id())
                    assert relay_conn1 is not None, "Failed to establish relay connection for client 1"
                    
                    # Try to open a stream over the relay connection
                    relay_stream1 = await client1_host.new_stream(target_host.get_id(), [test_protocol])
                    assert relay_stream1 is not None, "Failed to open stream over relay for client 1"
                    
                    # Send test message
                    await relay_stream1.write(TEST_MESSAGE)
                    
                    # Receive response
                    response = await relay_stream1.read(MAX_READ_LEN)
                    assert response == TEST_RESPONSE, f"Wrong response for client 1: {response}"
                    
                    logger.info("Client 1 relay connection successful")
            except Exception as e:
                logger.error(f"Client 1 relay test failed: {str(e)}")
                raise
            
            # Second client attempts to connect (should fail due to circuit limit)
            with pytest.raises(Exception):
                with trio.fail_after(RELAY_TIMEOUT):
                    logger.info("Client 2 attempting to dial target through relay (should fail)")
                    await client2_transport.dial_peer(target_host.get_id())
            
            # Cleanup the first connection to allow the second client to connect
            if relay_conn1:
                logger.info("Closing client 1 relay connection")
                await client1_host.disconnect(target_host.get_id())
                
                # Wait for connection to be cleaned up
                await trio.sleep(SLEEP_TIME * 2)
                
                # Now second client should be able to connect
                try:
                    with trio.fail_after(RELAY_TIMEOUT):
                        logger.info("Client 2 retrying connection after client 1 disconnected")
                        relay_conn2 = await client2_transport.dial_peer(target_host.get_id())
                        assert relay_conn2 is not None, "Failed to establish relay connection for client 2"
                        
                        # Try to open a stream over the relay connection
                        relay_stream2 = await client2_host.new_stream(target_host.get_id(), [test_protocol])
                        assert relay_stream2 is not None, "Failed to open stream over relay for client 2"
                        
                        # Send test message
                        await relay_stream2.write(TEST_MESSAGE)
                        
                        # Receive response
                        response = await relay_stream2.read(MAX_READ_LEN)
                        assert response == TEST_RESPONSE, f"Wrong response for client 2: {response}"
                        
                        logger.info("Client 2 relay connection successful after client 1 disconnected")
                except Exception as e:
                    logger.error(f"Client 2 relay test failed: {str(e)}")
                    raise 