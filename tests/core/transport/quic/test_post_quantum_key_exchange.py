"""
Post-quantum key exchange on the QUIC transport.

go-libp2p and rust-libp2p negotiate the hybrid TLS group X25519MLKEM768 on
QUIC by default. py-libp2p gets it from aioquic and sets no groups of its own,
so a dependency change could drop it without any py-libp2p test failing. The
handshake still completes with a classical group in that case, which is why
this test reads the TLS hello messages instead of only checking that the
connection comes up.

See https://github.com/libp2p/py-libp2p/issues/1581
"""

from dataclasses import dataclass, field

import pytest
from aioquic import tls
from aioquic.buffer import Buffer
import multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.utils import create_quic_multiaddr

# TLS NamedGroup code point (draft-ietf-tls-ecdhe-mlkem). Written out here so
# that the test fails on an assertion, not an AttributeError, when the
# installed aioquic has no such group.
X25519MLKEM768 = 0x11EC

HANDSHAKE_TIMEOUT = 10.0


@dataclass
class ObservedHellos:
    """TLS hello messages parsed by aioquic during a handshake."""

    # ClientHellos as the server parsed them. A second one means the client
    # answered a HelloRetryRequest.
    client_hellos: list[tls.ClientHello] = field(default_factory=list)
    # ServerHellos as the client parsed them. aioquic parses a
    # HelloRetryRequest as a ServerHello too.
    server_hellos: list[tls.ServerHello] = field(default_factory=list)


@pytest.fixture
def observed_hellos(monkeypatch: pytest.MonkeyPatch) -> ObservedHellos:
    """
    Record every ClientHello and ServerHello that aioquic parses.

    aioquic has no public API for the negotiated group, so the test observes
    the parsed messages. ``pull_client_hello`` and ``pull_server_hello`` are
    module-level functions which ``tls.Context`` looks up at call time.
    """
    observed = ObservedHellos()
    pull_client_hello = tls.pull_client_hello
    pull_server_hello = tls.pull_server_hello

    def record_client_hello(buf: Buffer) -> tls.ClientHello:
        hello = pull_client_hello(buf)
        observed.client_hellos.append(hello)
        return hello

    def record_server_hello(buf: Buffer) -> tls.ServerHello:
        hello = pull_server_hello(buf)
        observed.server_hellos.append(hello)
        return hello

    monkeypatch.setattr(tls, "pull_client_hello", record_client_hello)
    monkeypatch.setattr(tls, "pull_server_hello", record_server_hello)
    return observed


async def _handshake() -> None:
    """Complete one QUIC handshake between two py-libp2p transports."""
    server_key = create_new_key_pair()
    client_key = create_new_key_pair()
    config = QUICTransportConfig(idle_timeout=10.0, connection_timeout=5.0)
    server_transport = QUICTransport(server_key.private_key, config)
    client_transport = QUICTransport(client_key.private_key, config)

    async def server_handler(conn) -> None:
        await trio.sleep_forever()

    listener = server_transport.create_listener(server_handler)
    try:
        async with trio.open_nursery() as nursery:
            server_transport.set_background_nursery(nursery)
            client_transport.set_background_nursery(nursery)
            await listener.listen(create_quic_multiaddr("127.0.0.1", 0, "/quic"))
            server_addr = multiaddr.Multiaddr(
                f"{listener.get_addrs()[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
            )
            with trio.fail_after(HANDSHAKE_TIMEOUT):
                conn = await client_transport.dial(server_addr)
            await conn.close()
            nursery.cancel_scope.cancel()
    finally:
        if not listener._closed:
            await listener.close()
        await server_transport.close()
        await client_transport.close()


def assert_post_quantum_key_exchange(observed: ObservedHellos) -> None:
    """
    Fail unless the observed handshake used X25519MLKEM768.

    ``observed.client_hellos[i].supported_groups`` is the list of group code
    points the client offered, in preference order, and ``.key_share`` is a
    list of ``(group, public_bytes)``. ``observed.server_hellos[i].key_share``
    is the ``(group, bytes)`` the server chose, or ``None`` on a
    HelloRetryRequest, where ``.selected_group`` is set instead.
    """
    assert observed.client_hellos, "the server parsed no ClientHello"
    assert observed.server_hellos, "the client parsed no ServerHello"

    # Offered, and with a key share, so that the group does not depend on the
    # server asking for it with a HelloRetryRequest. Where it sits in the
    # client's order of preference is aioquic's policy and is not checked.
    first_client_hello = observed.client_hellos[0]
    offered_groups = first_client_hello.supported_groups or []
    assert X25519MLKEM768 in offered_groups, (
        f"the client did not offer X25519MLKEM768, only {offered_groups}. "
        "Post-quantum key exchange needs aioquic 1.9 or later"
    )
    offered_shares = [group for group, _ in first_client_hello.key_share or []]
    assert X25519MLKEM768 in offered_shares, (
        f"the client sent no X25519MLKEM768 key share, only {offered_shares}"
    )

    # Selected. The last ServerHello is the real one, after any
    # HelloRetryRequest, and carries the server's key share.
    server_key_share = observed.server_hellos[-1].key_share
    assert server_key_share is not None, "the last ServerHello has no key share"
    assert server_key_share[0] == X25519MLKEM768, (
        f"the server selected group {server_key_share[0]:#06x}, not X25519MLKEM768"
    )


@pytest.mark.trio
async def test_quic_handshake_uses_post_quantum_key_exchange(
    observed_hellos: ObservedHellos,
) -> None:
    await _handshake()

    assert_post_quantum_key_exchange(observed_hellos)
