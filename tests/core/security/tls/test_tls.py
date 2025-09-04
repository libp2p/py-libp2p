import pytest

from libp2p import generate_new_rsa_identity
from libp2p.security.tls.transport import TLSTransport
from tests.utils.factories import tls_conn_factory


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
