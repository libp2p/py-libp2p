from unittest.mock import (
    AsyncMock,
    MagicMock,
)

import pytest

from libp2p.custom_types import (
    TMuxerClass,
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.protocol_muxer.exceptions import (
    MultiselectError,
)
from libp2p.stream_muxer.muxer_multistream import (
    MuxerMultistream,
)


@pytest.mark.trio
async def test_muxer_timeout_configuration():
    """Test that muxer respects timeout configuration."""
    muxer = MuxerMultistream({}, negotiate_timeout=1)
    assert muxer.negotiate_timeout == 1


@pytest.mark.trio
async def test_select_transport_passes_timeout_to_multiselect():
    """Test that timeout is passed to multiselect client in select_transport."""
    # Mock dependencies
    mock_conn = MagicMock()
    mock_conn.is_initiator = False

    # Mock MultiselectClient
    muxer = MuxerMultistream({}, negotiate_timeout=10)
    muxer.multiselect.negotiate = AsyncMock(return_value=("mock_protocol", None))
    muxer.transports[TProtocol("mock_protocol")] = MagicMock(return_value=MagicMock())

    # Call select_transport
    await muxer.select_transport(mock_conn)

    # Verify that select_one_of was called with the correct timeout
    args, _ = muxer.multiselect.negotiate.call_args
    assert args[1] == 10


@pytest.mark.trio
async def test_new_conn_passes_timeout_to_multistream_client():
    """Test that timeout is passed to multistream client in new_conn."""
    # Mock dependencies
    mock_conn = MagicMock()
    mock_conn.is_initiator = True
    mock_peer_id = ID(b"test_peer")

    # Mock MultistreamClient and transports
    muxer = MuxerMultistream({}, negotiate_timeout=30)
    muxer.multistream_client.select_one_of = AsyncMock(return_value="mock_protocol")
    muxer.transports[TProtocol("mock_protocol")] = MagicMock(return_value=MagicMock())

    # Call new_conn
    await muxer.new_conn(mock_conn, mock_peer_id)

    # Verify that select_one_of was called with the correct timeout
    muxer.multistream_client.select_one_of.assert_called_once()
    assert muxer.multistream_client.select_one_of.call_args[0][2] == 30


@pytest.mark.trio
async def test_select_transport_no_protocol_selected():
    """
    Test that select_transport raises MultiselectError when no protocol is selected.
    """
    # Mock dependencies
    mock_conn = MagicMock()
    mock_conn.is_initiator = False

    # Mock Multiselect to return None
    muxer = MuxerMultistream({}, negotiate_timeout=30)
    muxer.multiselect.negotiate = AsyncMock(return_value=(None, None))

    # Expect MultiselectError to be raised
    with pytest.raises(MultiselectError, match="no protocol selected"):
        await muxer.select_transport(mock_conn)


@pytest.mark.trio
async def test_add_transport_updates_precedence():
    """Test that adding a transport updates protocol precedence."""
    # Mock transport classes
    mock_transport1 = MagicMock(spec=TMuxerClass)
    mock_transport2 = MagicMock(spec=TMuxerClass)

    # Initialize muxer and add transports
    muxer = MuxerMultistream({}, negotiate_timeout=30)
    muxer.add_transport(TProtocol("proto1"), mock_transport1)
    muxer.add_transport(TProtocol("proto2"), mock_transport2)

    # Verify transport order
    assert list(muxer.transports.keys()) == ["proto1", "proto2"]

    # Re-add proto1 to check if it moves to the end
    muxer.add_transport(TProtocol("proto1"), mock_transport1)
    assert list(muxer.transports.keys()) == ["proto2", "proto1"]
