from unittest.mock import (
    AsyncMock,
    MagicMock,
)

import pytest

from libp2p import (
    new_swarm,
)
from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.host.defaults import (
    get_default_protocols,
)
from libp2p.host.exceptions import (
    HostException,
    StreamFailure,
)


def test_default_protocols():
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    mux = host.get_mux()
    handlers = mux.handlers
    # NOTE: comparing keys for equality as handlers may be closures that do not compare
    # in the way this test is concerned with
    assert handlers.keys() == get_default_protocols(host).keys()


@pytest.mark.trio
async def test_swarm_stream_handler_no_protocol_selected(monkeypatch):
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    # Create a mock net_stream
    net_stream = MagicMock()
    net_stream.reset = AsyncMock()
    net_stream.muxed_conn.peer_id = "peer-test"

    # Monkeypatch negotiate to simulate "no protocol selected"
    async def fake_negotiate(comm, timeout):
        return None, None

    monkeypatch.setattr(host.multiselect, "negotiate", fake_negotiate)

    # Now run the handler and expect StreamFailure
    with pytest.raises(
        StreamFailure, match="Failed to negotiate protocol: no protocol selected"
    ):
        await host._swarm_stream_handler(net_stream)

    # Ensure reset was called since negotiation failed
    net_stream.reset.assert_awaited()


def test_set_stream_handler_success():
    """Test successful stream handler setting."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    async def mock_handler(stream):
        pass

    host.set_stream_handler("/test/protocol", mock_handler)
    
    assert "/test/protocol" in host.multiselect.handlers
    assert host.multiselect.handlers["/test/protocol"] == mock_handler


def test_set_stream_handler_empty_protocol():
    """Test set_stream_handler raises exception when protocol_id is empty."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    async def mock_handler(stream):
        pass

    with pytest.raises(HostException, match="Protocol ID cannot be empty"):
        host.set_stream_handler("", mock_handler)


def test_set_stream_handler_none_handler():
    """Test set_stream_handler raises exception when stream_handler is None."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    with pytest.raises(HostException, match="Stream handler cannot be None"):
        host.set_stream_handler("/test/protocol", None)


def test_set_stream_handler_exception_handling():
    """Test set_stream_handler properly handles exceptions from multiselect."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    async def mock_handler(stream):
        pass

    original_add_handler = host.multiselect.add_handler
    host.multiselect.add_handler = MagicMock(side_effect=RuntimeError("Test error"))

    with pytest.raises(HostException, match="Failed to set stream handler"):
        host.set_stream_handler("/test/protocol", mock_handler)

    host.multiselect.add_handler = original_add_handler


def test_set_stream_handler_multiple_exceptions():
    """Test set_stream_handler handles different types of exceptions."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    async def mock_handler(stream):
        pass

    # Test with ValueError
    original_add_handler = host.multiselect.add_handler
    host.multiselect.add_handler = MagicMock(side_effect=ValueError("Invalid value"))

    with pytest.raises(HostException, match="Failed to set stream handler"):
        host.set_stream_handler("/test/protocol", mock_handler)

    # Test with KeyError
    host.multiselect.add_handler = MagicMock(side_effect=KeyError("Missing key"))

    with pytest.raises(HostException, match="Failed to set stream handler"):
        host.set_stream_handler("/test/protocol", mock_handler)

    host.multiselect.add_handler = original_add_handler


def test_set_stream_handler_preserves_exception_chain():
    """Test that set_stream_handler preserves the original exception chain."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    async def mock_handler(stream):
        pass

    original_add_handler = host.multiselect.add_handler
    original_error = RuntimeError("Original error")
    host.multiselect.add_handler = MagicMock(side_effect=original_error)

    with pytest.raises(HostException) as exc_info:
        host.set_stream_handler("/test/protocol", mock_handler)

    # Check that the original exception is preserved in the chain
    assert exc_info.value.__cause__ is original_error
    assert "Failed to set stream handler" in str(exc_info.value)

    host.multiselect.add_handler = original_add_handler


def test_set_stream_handler_success_with_valid_inputs():
    """Test set_stream_handler succeeds with various valid protocol IDs."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    async def mock_handler(stream):
        pass

    # Test with different valid protocol IDs
    valid_protocols = [
        "/test/protocol",
        "/ipfs/id/1.0.0",
        "/libp2p/autonat/1.0.0",
        "/multistream/1.0.0",
        "/test/protocol/with/version/1.0.0"
    ]

    for protocol_id in valid_protocols:
        host.set_stream_handler(protocol_id, mock_handler)
        assert protocol_id in host.multiselect.handlers
        assert host.multiselect.handlers[protocol_id] == mock_handler


def test_set_stream_handler_edge_cases():
    """Test set_stream_handler with edge case inputs."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    async def mock_handler(stream):
        pass

    # Test with whitespace-only protocol ID
    with pytest.raises(HostException, match="Protocol ID cannot be empty"):
        host.set_stream_handler("   ", mock_handler)

    # Test with None protocol ID
    with pytest.raises(HostException, match="Protocol ID cannot be empty"):
        host.set_stream_handler(None, mock_handler)

    # Test with empty string protocol ID
    with pytest.raises(HostException, match="Protocol ID cannot be empty"):
        host.set_stream_handler("", mock_handler)
