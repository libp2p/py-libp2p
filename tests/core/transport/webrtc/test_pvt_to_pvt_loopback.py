import logging
from typing import Any, cast

import pytest
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import INetStream
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.transport.webrtc.constants import (
    DEFAULT_ICE_SERVERS,
)
from libp2p.transport.webrtc.multiaddr_protocols import register_webrtc_protocols
from libp2p.transport.webrtc.private_to_private import WebRTCTransport
from libp2p.transport.webrtc.private_to_private.listener import WebRTCPeerListener
from libp2p.transport.webrtc.private_to_private.signaling_stream_handler import (
    handle_incoming_stream,
)

logger = logging.getLogger("tests.webrtc.loopback.real")

# Register WebRTC multiaddr protocols
register_webrtc_protocols()


@pytest.fixture
def ice_configuration() -> RTCConfiguration:
    """Create RTCConfiguration with ICE servers for real WebRTC connections."""
    ice_servers = [
        RTCIceServer(**server) if not isinstance(server, RTCIceServer) else server
        for server in DEFAULT_ICE_SERVERS
    ]
    return RTCConfiguration(iceServers=ice_servers)


@pytest.fixture
def test_protocol() -> TProtocol:
    """Test protocol for echo handler."""
    return TProtocol("/libp2p/webrtc/test/1.0.0")


# ============================================================================
# REAL WEBRTC COMPONENT TESTS
# ============================================================================


@pytest.mark.trio
async def test_real_webrtc_transport_initialization():
    """Test real WebRTCTransport initialization."""
    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)

    transport = WebRTCTransport()
    transport.set_host(host)

    assert not transport.is_started()
    await transport.start()
    assert transport.is_started()

    assert "webrtc" in transport.get_supported_protocols()
    assert transport.get_connection_count() == 0

    await transport.stop()
    assert not transport.is_started()
    await host.close()


@pytest.mark.trio
async def test_real_webrtc_listener_creation():
    """Test real WebRTCPeerListener creation."""
    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)

    transport = WebRTCTransport()
    transport.set_host(host)
    await transport.start()

    async def dummy_handler(stream: Any) -> None:
        await stream.close()

    listener = cast(WebRTCPeerListener, transport.create_listener(dummy_handler))
    assert listener is not None
    assert not listener.is_listening()

    async with trio.open_nursery() as nursery:
        # Start listening (doesn't need real multiaddr for loopback)
        dummy_maddr = Multiaddr("/webrtc")
        success = await listener.listen(dummy_maddr, nursery)
        assert success
        assert listener.is_listening()

        addrs = listener.get_addrs()
        # Should have at least one address (generic WebRTC address)
        assert len(addrs) > 0

        await listener.close()
        assert not listener.is_listening()

    await transport.stop()
    await host.close()


@pytest.mark.trio
async def test_real_rtcpeerconnection_creation(ice_configuration):
    """Test creating real RTCPeerConnection from aiortc."""
    # This tests that we can actually create real WebRTC peer connections
    from trio_asyncio import open_loop

    async with open_loop():
        peer_connection = RTCPeerConnection(ice_configuration)
        assert peer_connection is not None
        assert peer_connection.connectionState == "new"

        # Create a data channel
        data_channel = peer_connection.createDataChannel("test-channel")
        assert data_channel is not None
        assert data_channel.label == "test-channel"

        # Cleanup
        await peer_connection.close()
        assert peer_connection.connectionState == "closed"


@pytest.mark.trio
async def test_real_webrtc_sdp_exchange(ice_configuration):
    """
    Test real WebRTC SDP offer/answer exchange.
    This creates two real RTCPeerConnections and exchanges SDP.
    """
    from trio_asyncio import aio_as_trio, open_loop

    async with open_loop():
        # Create two peer connections (simulating two peers)
        pc_a = RTCPeerConnection(ice_configuration)
        pc_b = RTCPeerConnection(ice_configuration)

        # Create data channel on initiator (pc_a)
        pc_a.createDataChannel("test")

        # Create offer
        offer = await aio_as_trio(pc_a.createOffer())
        assert offer is not None, "Expected SDP offer"
        await aio_as_trio(pc_a.setLocalDescription(offer))
        assert pc_a.localDescription is not None
        assert pc_a.localDescription.type == "offer"

        # Set remote description on responder (pc_b)
        await aio_as_trio(pc_b.setRemoteDescription(offer))

        # Create answer
        answer = await aio_as_trio(pc_b.createAnswer())
        assert answer is not None, "Expected SDP answer"
        await aio_as_trio(pc_b.setLocalDescription(answer))
        assert pc_b.localDescription is not None
        assert pc_b.localDescription.type == "answer"

        # Set answer on initiator
        await aio_as_trio(pc_a.setRemoteDescription(answer))

        # Verify connection states
        assert pc_a.remoteDescription is not None
        assert pc_b.remoteDescription is not None

        # Cleanup - use aio_as_trio for proper cleanup
        try:
            await aio_as_trio(pc_a.close())
        except Exception as e:
            logger.warning(f"Error closing pc_a: {e}")
        try:
            await aio_as_trio(pc_b.close())
        except Exception as e:
            logger.warning(f"Error closing pc_b: {e}")


@pytest.mark.trio
async def test_real_signaling_stream_handler(ice_configuration, test_protocol):
    """
    Test real signaling stream handler with actual WebRTC components.
    Creates a mock signaling stream and tests the handler.
    """
    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)

    # Create a simple in-memory stream for signaling
    class MockMuxedConn:
        def __init__(self, peer_id: ID) -> None:
            self.peer_id = peer_id

    class MockSignalingStream:
        """Simple in-memory stream for signaling (acceptable for loopback)."""

        def __init__(self):
            self._data_queue: list[bytes] = []
            self._closed = False

        async def read(self, _: int = -1) -> bytes:
            if self._closed:
                return b""
            if self._data_queue:
                return self._data_queue.pop(0)
            await trio.sleep(0.01)  # Wait a bit
            return b"" if self._closed else b""

        async def write(self, data: bytes) -> None:
            if not self._closed:
                self._data_queue.append(data)

        async def close(self) -> None:
            self._closed = True

        @property
        def muxed_conn(self):
            """Return mock muxed connection with peer_id."""
            return MockMuxedConn(ID.from_pubkey(key_pair.public_key))

    # Create signaling stream
    signaling_stream = MockSignalingStream()

    # Create RTCConfiguration
    rtc_config = ice_configuration

    # Create peer connection and offer (simulating initiator)
    from trio_asyncio import aio_as_trio, open_loop

    from libp2p.transport.webrtc.private_to_private.pb.message_pb2 import Message

    async with open_loop():
        initiator_pc = RTCPeerConnection(rtc_config)
        initiator_pc.createDataChannel("libp2p-webrtc")

        # Create and send offer through signaling stream
        offer = await aio_as_trio(initiator_pc.createOffer())
        assert offer is not None, "Expected SDP offer"
        await aio_as_trio(initiator_pc.setLocalDescription(offer))

        # Serialize offer to signaling stream
        offer_msg = Message()
        offer_msg.type = Message.Type.SDP_OFFER
        offer_msg.data = offer.sdp
        await signaling_stream.write(offer_msg.SerializeToString())

        # Handle incoming stream (this is the REAL handler function)
        connection_info = {"peer_id": ID.from_pubkey(key_pair.public_key)}
        result = await handle_incoming_stream(
            stream=cast(INetStream, signaling_stream),
            rtc_config=rtc_config,
            connection_info=connection_info,
            host=host,
            timeout=10.0,
        )

        # Verify connection was established
        assert result is not None
        assert hasattr(result, "peer_connection")
        assert hasattr(result, "data_channel")

        # Cleanup
        if result:
            try:
                await result.close()
            except Exception as e:
                logger.warning(f"Error closing result: {e}")
        try:
            await aio_as_trio(initiator_pc.close())
        except Exception as e:
            logger.warning(f"Error closing initiator_pc: {e}")
        await host.close()


@pytest.mark.trio
async def test_real_webrtc_data_transmission(ice_configuration):
    """
    Test REAL data transmission over WebRTC data channel.
    Creates two peer connections, establishes connection, and transmits data.
    """
    from trio_asyncio import aio_as_trio, open_loop

    async with open_loop():
        # Create two peer connections
        pc_a = RTCPeerConnection(ice_configuration)
        pc_b = RTCPeerConnection(ice_configuration)

        # Events for coordination
        data_channel_ready = trio.Event()
        received_data: list[bytes] = []

        def on_data_channel(channel):
            def on_message(event):
                received_data.append(event.data if hasattr(event, "data") else event)

            def on_open():
                data_channel_ready.set()

            channel.on("message", on_message)
            channel.on("open", on_open)

        pc_b.on("datachannel", on_data_channel)

        # Create data channel on pc_a (initiator)
        data_channel = pc_a.createDataChannel("test")
        data_sent = trio.Event()

        def on_channel_open():
            data_sent.set()

        data_channel.on("open", on_channel_open)

        # Exchange SDP
        offer = await aio_as_trio(pc_a.createOffer())
        assert offer is not None, "Expected SDP offer"
        await aio_as_trio(pc_a.setLocalDescription(offer))
        await aio_as_trio(pc_b.setRemoteDescription(offer))

        answer = await aio_as_trio(pc_b.createAnswer())
        assert answer is not None, "Expected SDP answer"
        await aio_as_trio(pc_b.setLocalDescription(answer))
        await aio_as_trio(pc_a.setRemoteDescription(answer))

        # Wait for data channel to be ready (both initiator and responder)
        with trio.move_on_after(10.0):
            await data_sent.wait()
            await data_channel_ready.wait()

        # Ensure data channel is actually open before sending
        if data_channel.readyState != "open":
            await trio.sleep(0.5)  # Wait a bit more for state to update
            if data_channel.readyState != "open":
                state = data_channel.readyState
                raise AssertionError(f"Data channel not open, state: {state}")

        # Send test data
        test_data = b"Hello from real WebRTC test!"
        if data_channel.readyState == "open":
            data_channel.send(test_data)
        else:
            state = data_channel.readyState
            raise AssertionError(f"Cannot send data, channel state: {state}")

        # Wait for data to be received
        await trio.sleep(0.5)  # Give time for message to propagate

        # Verify data was received
        assert len(received_data) > 0
        # Check if data matches (handle different message formats)
        for data in received_data:
            if isinstance(data, bytes) and test_data in data:
                break
            if isinstance(data, str) and test_data.decode() in data:
                break
        else:
            raise AssertionError("Expected payload not received over WebRTC channel")

        # Cleanup - use aio_as_trio for proper cleanup
        try:
            await aio_as_trio(pc_a.close())
        except Exception as e:
            logger.warning(f"Error closing pc_a: {e}")
        try:
            await aio_as_trio(pc_b.close())
        except Exception as e:
            logger.warning(f"Error closing pc_b: {e}")


# ============================================================================
# INTEGRATION TESTS - Full Transport Stack
# ============================================================================


@pytest.mark.trio
async def test_real_webrtc_transport_with_host():
    """
    Test real WebRTCTransport integrated with libp2p host.
    Verifies transport registration and signaling handler setup.
    """
    key_pair = create_new_key_pair()
    host = new_host(key_pair=key_pair)

    transport = WebRTCTransport()
    transport.set_host(host)
    await transport.start()

    # Verify signaling protocol handler is registered
    # (This is done in transport.start())
    assert transport.is_started()

    # Create listener
    async def handler(stream: Any) -> None:
        await stream.close()

    listener = cast(WebRTCPeerListener, transport.create_listener(handler))
    assert listener is not None

    async with trio.open_nursery() as nursery:
        dummy_maddr = Multiaddr("/webrtc")
        success = await listener.listen(dummy_maddr, nursery)
        assert success

        addrs = listener.get_addrs()
        assert len(addrs) > 0
        logger.info(f"WebRTC listener addresses: {addrs}")

        await listener.close()

    await transport.stop()
    await host.close()


@pytest.mark.skip(
    reason="Requires circuit relay for full end-to-end test. "
    "This would need a relay node or simplified in-process signaling."
)
@pytest.mark.trio
async def test_real_webrtc_full_connection_loopback():
    """
    Full end-to-end test with real WebRTC connection.

    NOTE: This requires either:
    1. Circuit relay setup in-process
    2. Direct signaling mechanism for loopback
    3. Simplified signaling bypass for testing

    Currently skipped because initiate_connection requires relay.
    """
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()

    host_a = new_host(key_pair=key_pair_a)
    host_b = new_host(key_pair=key_pair_b)

    transport_a = WebRTCTransport()
    transport_b = WebRTCTransport()

    transport_a.set_host(host_a)
    transport_b.set_host(host_b)

    await transport_a.start()
    await transport_b.start()

    # This test would:
    # 1. Set up listeners on both hosts
    # 2. Get WebRTC multiaddrs
    # 3. Establish signaling connection
    # 4. Complete WebRTC handshake
    # 5. Transmit data
    # 6. Verify receipt

    await transport_a.stop()
    await transport_b.stop()
    await host_a.close()
    await host_b.close()
