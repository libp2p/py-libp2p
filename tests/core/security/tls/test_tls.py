from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from libp2p import generate_new_rsa_identity
from libp2p.peer.id import ID
from libp2p.security.exceptions import HandshakeFailure
from libp2p.security.tls.exceptions import TLSHandshakeFailure
from libp2p.security.tls.transport import TLSTransport
from libp2p.transport.exceptions import SecurityUpgradeFailure
from libp2p.transport.upgrader import TransportUpgrader
from tests.utils.factories import (
    TLS_PROTOCOL_ID,
    default_mplex_muxer_transport_factory,
    raw_conn_factory,
    security_options_factory_factory,
    tls_conn_factory,
)


def test_tls_handshake_failure_extends_central_handshake_failure() -> None:
    assert issubclass(TLSHandshakeFailure, HandshakeFailure)


def _mock_tls_reader_writer_no_cert() -> MagicMock:
    mock_rw = MagicMock()
    mock_rw.handshake = AsyncMock()
    mock_rw.get_peer_certificate.return_value = None
    return mock_rw


@pytest.mark.trio
async def test_secure_inbound_rejects_missing_client_certificate() -> None:
    keypair = generate_new_rsa_identity()
    transport = TLSTransport(keypair, enable_autotls=False)
    mock_conn = MagicMock()
    mock_rw = _mock_tls_reader_writer_no_cert()

    with patch(
        "libp2p.security.tls.transport.TLSReadWriter", return_value=mock_rw
    ), pytest.raises(TLSHandshakeFailure, match="no client certificate"):
        await transport.secure_inbound(mock_conn)


@pytest.mark.trio
async def test_upgrader_rejects_missing_client_certificate(nursery) -> None:
    keypair = generate_new_rsa_identity()
    sec_opt = security_options_factory_factory(TLS_PROTOCOL_ID)(keypair)
    upgrader = TransportUpgrader(sec_opt, default_mplex_muxer_transport_factory())
    mock_rw = _mock_tls_reader_writer_no_cert()

    with patch(
        "libp2p.security.tls.transport.TLSReadWriter", return_value=mock_rw
    ):
        async with raw_conn_factory(nursery) as (_local_conn, remote_conn):
            with pytest.raises(SecurityUpgradeFailure):
                await upgrader.upgrade_security(remote_conn, False)


@pytest.mark.trio
async def test_secure_inbound_autotls_allows_primitive_exchange_identity() -> None:
    server_keypair = generate_new_rsa_identity()
    client_keypair = generate_new_rsa_identity()
    transport = TLSTransport(server_keypair, enable_autotls=True)
    mock_conn = MagicMock()
    mock_rw = _mock_tls_reader_writer_no_cert()
    mock_rw.remote_primitive_pk = client_keypair.public_key
    mock_rw.remote_primitive_peerid = ID.from_pubkey(client_keypair.public_key)

    with patch("libp2p.security.tls.transport.TLSReadWriter", return_value=mock_rw):
        session = await transport.secure_inbound(mock_conn)

    assert session.get_remote_peer() == ID.from_pubkey(client_keypair.public_key)


@pytest.mark.trio
async def test_tls_basic_handshake(nursery):
    keypair_a = generate_new_rsa_identity()
    keypair_b = generate_new_rsa_identity()

    t_a = TLSTransport(keypair_a)
    t_b = TLSTransport(keypair_b)
    # Trust each other's certs during tests to avoid system verify failure
    t_a.trust_peer_cert_pem(t_b.get_certificate_pem())
    t_b.trust_peer_cert_pem(t_a.get_certificate_pem())

    async with tls_conn_factory(
        nursery, client_transport=t_a, server_transport=t_b
    ) as (
        client_conn,
        server_conn,
    ):
        assert client_conn.get_local_peer() == t_a.local_peer
        assert server_conn.get_local_peer() == t_b.local_peer
        assert client_conn.get_remote_peer() == t_b.local_peer
        assert server_conn.get_remote_peer() == t_a.local_peer

        await server_conn.write(b"hello")
        assert await client_conn.read(5) == b"hello"

        await client_conn.write(b"world")
        assert await server_conn.read(5) == b"world"

        await client_conn.close()
        await server_conn.close()


DATA_0 = b"hello"
DATA_1 = b"x" * 1500
DATA_2 = b"bye!"


@pytest.mark.trio
async def test_tls_transport(nursery):
    async with tls_conn_factory(nursery):
        # handshake succeeds if factory returns
        pass


@pytest.mark.trio
async def test_tls_connection(nursery):
    async with tls_conn_factory(nursery) as (local, remote):
        await local.write(DATA_0)
        await local.write(DATA_1)

        assert DATA_0 == await remote.read(len(DATA_0))
        assert DATA_1 == await remote.read(len(DATA_1))

        await local.write(DATA_2)
        assert DATA_2 == await remote.read(len(DATA_2))
