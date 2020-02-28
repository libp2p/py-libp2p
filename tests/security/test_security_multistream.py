import pytest

from libp2p.crypto.rsa import create_new_key_pair
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureSession
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
from libp2p.security.secio.transport import ID as SECIO_PROTOCOL_ID
from libp2p.security.secure_session import SecureSession
from libp2p.tools.factories import host_pair_factory

initiator_key_pair = create_new_key_pair()

noninitiator_key_pair = create_new_key_pair()


async def perform_simple_test(assertion_func, security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as hosts:
        conn_0 = hosts[0].get_network().connections[hosts[1].get_id()]
        conn_1 = hosts[1].get_network().connections[hosts[0].get_id()]

        # Perform assertion
        assertion_func(conn_0.muxed_conn.secured_conn)
        assertion_func(conn_1.muxed_conn.secured_conn)


@pytest.mark.trio
@pytest.mark.parametrize(
    "security_protocol, transport_type",
    (
        (PLAINTEXT_PROTOCOL_ID, InsecureSession),
        (SECIO_PROTOCOL_ID, SecureSession),
        (NOISE_PROTOCOL_ID, SecureSession),
    ),
)
@pytest.mark.trio
async def test_single_insecure_security_transport_succeeds(
    security_protocol, transport_type
):
    def assertion_func(conn):
        assert isinstance(conn, transport_type)

    await perform_simple_test(assertion_func, security_protocol)


@pytest.mark.trio
async def test_default_insecure_security():
    def assertion_func(conn):
        assert isinstance(conn, InsecureSession)

    await perform_simple_test(assertion_func, None)
