"""
Promotion must stop treating an established inbound connection as pending.

The listener's periodic cleanup closes any connection whose pending CID is no
longer in the registry's pending table. A promoted connection is exactly that
until its pending-tracking entry is dropped, so leaving it behind closes live
inbound connections on the next sweep (about ten seconds after handshake).
"""

import pytest
import multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.utils import create_quic_multiaddr


@pytest.mark.trio
async def test_promoted_inbound_connection_leaves_pending_tracking() -> None:
    server_key = create_new_key_pair()
    server_transport = QUICTransport(server_key.private_key, QUICTransportConfig())
    state: dict[str, object] = {}

    async def handler(connection: object) -> None:
        state["connection"] = connection
        await trio.sleep_forever()

    listener = server_transport.create_listener(handler)
    client_transport = None
    try:
        await listener.listen(create_quic_multiaddr("127.0.0.1", 0, "/quic"))
        peer_addr = multiaddr.Multiaddr(
            f"{listener.get_addrs()[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
        )

        async with trio.open_nursery() as nursery:
            client_transport = QUICTransport(
                create_new_key_pair().private_key, QUICTransportConfig()
            )
            client_transport.set_background_nursery(nursery)
            client = await client_transport.dial(peer_addr)
            stream = await client.open_stream()
            await stream.write(b"hello")
            with trio.fail_after(8.0):
                while "connection" not in state:
                    await trio.sleep(0.02)

            server_connection = state["connection"]
            quic_key = id(server_connection._quic)  # type: ignore[attr-defined]

            # The connection is live and deduplicated by quic identity ...
            assert quic_key in listener._conn_by_quic_id
            # ... but it is no longer a pending handshake. If this entry stays,
            # the periodic cleanup treats it as an orphan and closes it.
            assert quic_key not in listener._pending_cid_by_quic_id
            assert not server_connection.is_closed  # type: ignore[attr-defined]

            await client_transport.close()
            nursery.cancel_scope.cancel()
    finally:
        await listener.close()
        if client_transport is not None:
            await client_transport.close()
        await server_transport.close()
