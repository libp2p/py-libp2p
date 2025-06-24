import pytest
import trio

from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureSession,
)
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
from libp2p.security.secio.transport import ID as SECIO_PROTOCOL_ID
from libp2p.security.secure_session import (
    SecureSession,
)
from libp2p.stream_muxer.mplex.mplex import Mplex
from libp2p.stream_muxer.yamux.yamux import Yamux
from tests.utils.factories import (
    host_pair_factory,
)

initiator_key_pair = create_new_key_pair()

noninitiator_key_pair = create_new_key_pair()


async def perform_simple_test(assertion_func, security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as hosts:
        # Use a different approach to verify connections
        # Wait for both sides to establish connection
        for _ in range(5):  # Try up to 5 times
            try:
                # Check if connection established from host0 to host1
                conn_0 = hosts[0].get_network().connections.get(hosts[1].get_id())
                # Check if connection established from host1 to host0
                conn_1 = hosts[1].get_network().connections.get(hosts[0].get_id())

                if conn_0 and conn_1:
                    break

                # Wait a bit and retry
                await trio.sleep(0.2)
            except Exception:
                # Wait a bit and retry
                await trio.sleep(0.2)

        # If we couldn't establish connection after retries,
        # the test will fail with clear error
        assert conn_0 is not None, "Failed to establish connection from host0 to host1"
        assert conn_1 is not None, "Failed to establish connection from host1 to host0"

        # Extract the secured connection from either Mplex or Yamux implementation
        def get_secured_conn(conn):
            muxed_conn = conn.muxed_conn
            # Direct attribute access for known implementations
            has_secured_conn = hasattr(muxed_conn, "secured_conn")
            if isinstance(muxed_conn, (Mplex, Yamux)) and has_secured_conn:
                return muxed_conn.secured_conn
            # Fallback to _connection attribute if it exists
            elif hasattr(muxed_conn, "_connection"):
                return muxed_conn._connection
            # Last resort - warn but return the muxed_conn itself for type checking
            else:
                print(f"Warning: Cannot find secured connection in {type(muxed_conn)}")
                return muxed_conn

        # Get secured connections for both peers
        secured_conn_0 = get_secured_conn(conn_0)
        secured_conn_1 = get_secured_conn(conn_1)

        # Perform assertion on the secured connections
        assertion_func(secured_conn_0)
        assertion_func(secured_conn_1)


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
