from unittest.mock import (
    AsyncMock,
    MagicMock,
)

import pytest
from multiaddr import Multiaddr

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


def test_get_addrs_and_transport_addrs():
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    # Mock the network listeners
    mock_transport = MagicMock()
    raw_addr = Multiaddr("/ip4/127.0.0.1/tcp/8000")
    mock_transport.get_addrs.return_value = [raw_addr]

    # Inject into swarm listeners
    # swarm.listeners is a dict
    swarm.listeners = {"tcp": mock_transport}

    # Test get_transport_addrs
    transport_addrs = host.get_transport_addrs()
    assert len(transport_addrs) == 1
    assert transport_addrs[0] == raw_addr
    assert str(transport_addrs[0]) == "/ip4/127.0.0.1/tcp/8000"

    # Test get_addrs
    addrs = host.get_addrs()
    assert len(addrs) == 1
    addr_str = str(addrs[0])
    peer_id_str = str(host.get_id())
    assert peer_id_str in addr_str
    # multiaddr might normalize /p2p/ to /ipfs/
    assert addr_str.endswith(f"/p2p/{peer_id_str}") or addr_str.endswith(
        f"/ipfs/{peer_id_str}"
    )
