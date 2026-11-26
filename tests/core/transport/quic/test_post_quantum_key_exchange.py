"""
Post-quantum key exchange on the QUIC transport.

go-libp2p and rust-libp2p negotiate the hybrid TLS group X25519MLKEM768 on
QUIC by default. py-libp2p gets it from aioquic and sets no groups of its own,
so a dependency change could drop it without any py-libp2p test failing. The
handshake still completes with a classical group in that case, which is why
this test reads the TLS hello messages instead of only checking that the
connection comes up.

The hellos are read from the wire. The dialer reaches the listener through a
UDP relay that keeps every datagram, and the QUIC Initial packets among them
are decoded with keys any observer can derive. Nothing in aioquic is patched
or inspected.

See https://github.com/libp2p/py-libp2p/issues/1581
"""

import pytest
import multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.utils import create_quic_multiaddr
from tests.utils.quic_initial_hellos import (
    Direction,
    ObservedHellos,
    derive_initial_keys,
    observe_hellos,
)

# TLS NamedGroup code point (draft-ietf-tls-ecdhe-mlkem).
X25519MLKEM768 = 0x11EC

LOOPBACK = "127.0.0.1"
HANDSHAKE_TIMEOUT = 10.0
MAX_DATAGRAM_SIZE = 65536

Datagrams = list[tuple[Direction, bytes]]


async def _relay(
    relay_socket: trio.socket.SocketType,
    server_address: tuple[str, int],
    datagrams: Datagrams,
) -> None:
    """
    Forward datagrams between one client and the server, keeping a copy.

    Whatever does not come from the server is taken to come from the client,
    which is enough for a single dialer on loopback.
    """
    client_address: tuple[str, int] | None = None
    while True:
        data, address = await relay_socket.recvfrom(MAX_DATAGRAM_SIZE)
        if address == server_address:
            datagrams.append(("server_to_client", data))
            if client_address is not None:
                await relay_socket.sendto(data, client_address)
        else:
            client_address = address
            datagrams.append(("client_to_server", data))
            await relay_socket.sendto(data, server_address)


async def _handshake_through_relay() -> Datagrams:
    """
    Complete one QUIC handshake between two py-libp2p transports.

    Returns every datagram the two sides exchanged, in order.
    """
    server_key = create_new_key_pair()
    client_key = create_new_key_pair()
    config = QUICTransportConfig(idle_timeout=10.0, connection_timeout=5.0)
    server_transport = QUICTransport(server_key.private_key, config)
    client_transport = QUICTransport(client_key.private_key, config)
    datagrams: Datagrams = []

    async def server_handler(conn: QUICConnection) -> None:
        await trio.sleep_forever()

    listener = server_transport.create_listener(server_handler)
    relay_socket = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
    try:
        await relay_socket.bind((LOOPBACK, 0))
        async with trio.open_nursery() as nursery:
            server_transport.set_background_nursery(nursery)
            client_transport.set_background_nursery(nursery)
            await listener.listen(create_quic_multiaddr(LOOPBACK, 0))
            listen_port = listener.get_addrs()[0].value_for_protocol("udp")
            assert listen_port is not None, "the listener has no UDP port"
            server_port = int(listen_port)
            nursery.start_soon(_relay, relay_socket, (LOOPBACK, server_port), datagrams)

            relay_port = relay_socket.getsockname()[1]
            relay_addr = create_quic_multiaddr(LOOPBACK, relay_port)
            server_peer_id = ID.from_pubkey(server_key.public_key)
            with trio.fail_after(HANDSHAKE_TIMEOUT):
                conn = await client_transport.dial(
                    multiaddr.Multiaddr(f"{relay_addr}/p2p/{server_peer_id}")
                )
            await conn.close()
            nursery.cancel_scope.cancel()
    finally:
        relay_socket.close()
        if not listener._closed:
            await listener.close()
        await server_transport.close()
        await client_transport.close()
    return datagrams


def assert_post_quantum_key_exchange(observed: ObservedHellos) -> None:
    """Fail unless the observed handshake used X25519MLKEM768."""
    assert observed.client_hellos, "no ClientHello in the client's Initial packets"
    assert observed.server_hellos, "no ServerHello in the server's Initial packets"

    # Offered, and with a key share, so that the group does not depend on the
    # server asking for it with a HelloRetryRequest. Where it sits in the
    # client's order of preference is aioquic's policy and is not checked.
    first_client_hello = observed.client_hellos[0]
    offered_groups = [f"{g:#06x}" for g in first_client_hello.supported_groups]
    assert X25519MLKEM768 in first_client_hello.supported_groups, (
        f"the client did not offer X25519MLKEM768, only {offered_groups}. "
        "Post-quantum key exchange needs aioquic 1.9 or later"
    )
    offered_shares = [f"{g:#06x}" for g in first_client_hello.key_share_groups]
    assert X25519MLKEM768 in first_client_hello.key_share_groups, (
        f"the client sent no X25519MLKEM768 key share, only {offered_shares}"
    )

    # Selected. The last ServerHello is the real one, after any
    # HelloRetryRequest, and carries the server's key share.
    server_hello = observed.server_hellos[-1]
    assert not server_hello.is_hello_retry_request, (
        "the handshake ended on a HelloRetryRequest"
    )
    assert server_hello.selected_group is not None, "the ServerHello has no key share"
    assert server_hello.selected_group == X25519MLKEM768, (
        f"the server selected group {server_hello.selected_group:#06x}, "
        "not X25519MLKEM768"
    )


def test_initial_keys_match_rfc_9001_appendix_a1() -> None:
    # The decoder is only as good as its key schedule, so pin that to the
    # published vector for Destination Connection ID 0x8394c8f03e515708.
    keys = derive_initial_keys(bytes.fromhex("8394c8f03e515708"), "client")

    assert keys.key.hex() == "1f369613dd76d5467730efcbe3b1a22d"
    assert keys.iv.hex() == "fa044b2f42a3fd3b46fb255c"
    assert keys.header_protection.hex() == "9f50449e04a0e810283a1e9933adedd2"


@pytest.mark.trio
async def test_quic_handshake_uses_post_quantum_key_exchange() -> None:
    datagrams = await _handshake_through_relay()

    assert_post_quantum_key_exchange(observe_hellos(datagrams))
