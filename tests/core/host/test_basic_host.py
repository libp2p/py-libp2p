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
