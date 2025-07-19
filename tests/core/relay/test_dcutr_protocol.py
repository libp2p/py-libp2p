"""Tests for the Direct Connection Upgrade through Relay (DCUtR) protocol."""

import logging
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import trio

from libp2p.peer.id import (
    ID,
)
from libp2p.relay.circuit_v2.dcutr import (
    CONNECT_TYPE,
    SYNC_TYPE,
    DCUtRProtocol,
)
from libp2p.relay.circuit_v2.pb.dcutr_pb2 import (
    HolePunch,
)
from libp2p.tools.async_service import (
    background_trio_service,
)

logger = logging.getLogger(__name__)

# Test timeouts
SLEEP_TIME = 1.0  # seconds

# Maximum message size for DCUtR (4KiB as per spec)
MAX_MESSAGE_SIZE = 4 * 1024


@pytest.mark.trio
async def test_dcutr_protocol_initialization():
    """Test basic initialization of the DCUtR protocol."""
    # Create a mock host
    mock_host = MagicMock()
    mock_host._stream_handlers = {}

    # Mock the set_stream_handler method
    mock_host.set_stream_handler = AsyncMock()

    # Create a patched version of DCUtRProtocol that doesn't try to register handlers
    with patch("libp2p.relay.circuit_v2.dcutr.DCUtRProtocol.run") as mock_run:
        # Make mock_run return a coroutine
        async def mock_run_impl(*, task_status=trio.TASK_STATUS_IGNORED):
            # Set event_started
            task_status.started()
            # Instead of waiting forever, just return after a short delay
            await trio.sleep(0.1)

        mock_run.side_effect = mock_run_impl

        # Create the DCUtR protocol
        dcutr_protocol = DCUtRProtocol(mock_host)

        # Start the protocol with a timeout
        with trio.move_on_after(5):  # 5 second timeout
            async with background_trio_service(dcutr_protocol):
                # Wait for the protocol to start
                await dcutr_protocol.event_started.wait()

                # Verify run was called
                assert mock_run.called

                # Wait a bit to ensure everything is set up
                await trio.sleep(SLEEP_TIME)


@pytest.mark.trio
async def test_dcutr_message_exchange():
    """Test the exchange of DCUtR protocol messages between peers."""
    # Create mock hosts
    mock_host1 = MagicMock()
    mock_host1._stream_handlers = {}
    mock_host2 = MagicMock()
    mock_host2._stream_handlers = {}

    # Mock stream for communication
    mock_stream = MagicMock()
    mock_stream.read = AsyncMock()
    mock_stream.write = AsyncMock()
    mock_stream.close = AsyncMock()
    mock_stream.muxed_conn = MagicMock()

    # Set up mock read responses
    connect_response = HolePunch()
    # Use HolePunch.Type enum value directly
    connect_response.type = cast(HolePunch.Type, CONNECT_TYPE)
    connect_response.ObsAddrs.append(b"/ip4/192.168.1.1/tcp/1234")
    connect_response.ObsAddrs.append(b"/ip4/10.0.0.1/tcp/4321")

    sync_response = HolePunch()
    # Use HolePunch.Type enum value directly
    sync_response.type = cast(HolePunch.Type, SYNC_TYPE)

    # Configure the mock stream to return our responses
    mock_stream.read.side_effect = [
        connect_response.SerializeToString(),
        sync_response.SerializeToString(),
    ]

    # Mock peer ID with proper bytes
    peer_id_bytes = (
        b"\x12\x20\x8a\xb7\x89\xa5\x84\x54\xb4\x9b\x14\x93\x7c\xda\x1a\xb8"
        b"\x2e\x36\x33\x0f\x31\x10\x95\x39\x93\x9c\xee\x99\x62\x72\x6e\x5c\x1d"
    )
    mock_peer_id = ID(peer_id_bytes)
    mock_stream.muxed_conn.peer_id = mock_peer_id

    # Mock the set_stream_handler and new_stream methods
    mock_host1.set_stream_handler = AsyncMock()
    mock_host1.new_stream = AsyncMock(return_value=mock_stream)

    # Mock methods to make the test pass
    with patch(
        "libp2p.relay.circuit_v2.dcutr.DCUtRProtocol._perform_hole_punch"
    ) as mock_perform_hole_punch:
        # Make mock_perform_hole_punch return True
        mock_perform_hole_punch.return_value = True

        # Create DCUtR protocol
        dcutr = DCUtRProtocol(mock_host1)

        # Patch the run method
        with patch.object(dcutr, "run") as mock_run:
            # Make mock_run return a coroutine
            async def mock_run_impl(*, task_status=trio.TASK_STATUS_IGNORED):
                # Set event_started
                task_status.started()
                # Instead of waiting forever, just return after a short delay
                await trio.sleep(0.1)

            mock_run.side_effect = mock_run_impl

            # Start the protocol with a timeout
            with trio.move_on_after(5):  # 5 second timeout
                async with background_trio_service(dcutr):
                    # Wait for the protocol to start
                    await dcutr.event_started.wait()

                    # Simulate initiating a hole punch
                    success = await dcutr.initiate_hole_punch(mock_peer_id)

                    # Verify the hole punch was successful
                    assert success is True

                    # Verify the stream interactions
                    assert mock_host1.new_stream.called
                    assert mock_stream.write.called
                    assert mock_stream.read.called
                    assert mock_stream.close.called
