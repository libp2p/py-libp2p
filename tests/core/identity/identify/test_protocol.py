import logging

import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from libp2p.identity.identify.protocol import (
    AGENT_VERSION,
    ID,
    PROTOCOL_VERSION,
    _mk_identify_protobuf,
    _multiaddr_to_bytes,
    _remote_address_to_multiaddr,
)
from tests.factories import (
    host_pair_factory,
)


def clean_multiaddr(addr: Multiaddr) -> Multiaddr:
    """
    Clean a multiaddr by removing the '/p2p/' part if it exists.

    Args:
        addr: The multiaddr to clean

    Returns:
        The cleaned multiaddr
    """
    return Multiaddr.join(
        *(
            addr.split()[:-1]
            if str(addr.split()[-1]).startswith("/p2p/")
            else addr.split()
        )
    )


# logger = logging.getLogger("libp2p.identity.identify-test")
logger = logging.getLogger(__name__)


@pytest.mark.trio
async def test_identify_protocol(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Here, host_b is the requester and host_a is the responder.
        # observed_addr represent host_b's address as observed by host_a
        # (i.e., the address from which host_b's request was received).
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read()
        await stream.close()

        identify_response = Identify()
        identify_response.ParseFromString(response)

        logger.debug("host_a: %s", host_a.get_addrs())
        logger.debug("host_b: %s", host_b.get_addrs())

        # Check protocol version
        assert identify_response.protocol_version == PROTOCOL_VERSION

        # Check agent version
        assert identify_response.agent_version == AGENT_VERSION

        # Check public key
        assert identify_response.public_key == host_a.get_public_key().serialize()

        # Check listen addresses
        assert identify_response.listen_addrs == list(
            map(_multiaddr_to_bytes, host_a.get_addrs())
        )

        # Check observed address
        # TODO: use decapsulateCode(protocols('p2p').code)
        # when the Multiaddr class will implement it
        host_b_addr = host_b.get_addrs()[0]
        cleaned_addr = clean_multiaddr(host_b_addr)

        logger.debug("observed_addr: %s", Multiaddr(identify_response.observed_addr))
        logger.debug("host_b.get_addrs()[0]: %s", host_b.get_addrs()[0])
        logger.debug("cleaned_addr= %s", cleaned_addr)
        assert identify_response.observed_addr == _multiaddr_to_bytes(cleaned_addr)

        # Check protocols
        assert set(identify_response.protocols) == set(host_a.get_mux().get_protocols())

        # sanity check
        assert identify_response == _mk_identify_protobuf(host_a, cleaned_addr)


@pytest.mark.trio
async def test_complete_remote_address_delegation_chain(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        logger.debug(
            "test_complete_remote_address_delegation_chain security_protocol: %s",
            security_protocol,
        )

        # Create a stream from host_a to host_b
        stream = await host_a.new_stream(host_b.get_id(), (ID,))

        # Get references to all components in the delegation chain
        mplex_stream = stream.muxed_stream
        swarm_conn = host_a.get_network().connections[host_b.get_id()]
        mplex = swarm_conn.muxed_conn
        secure_session = mplex.secured_conn
        raw_connection = secure_session.conn
        trio_tcp_stream = raw_connection.stream

        # Get remote addresses at each layer
        stream_addr = stream.get_remote_address()
        muxed_stream_addr = stream.muxed_stream.get_remote_address()
        mplex_addr = mplex_stream.muxed_conn.get_remote_address()
        secure_session_addr = mplex.secured_conn.get_remote_address()
        raw_connection_addr = secure_session.conn.get_remote_address()
        trio_tcp_stream_addr = raw_connection.stream.get_remote_address()
        socket_addr = trio_tcp_stream.stream.socket.getpeername()

        # Log all addresses
        logger.debug("NetStream address: %s", stream_addr)
        logger.debug("MplexStream address: %s", muxed_stream_addr)
        logger.debug("Mplex address: %s", mplex_addr)
        logger.debug("SecureSession address: %s", secure_session_addr)
        logger.debug("RawConnection address: %s", raw_connection_addr)
        logger.debug("TrioTCPStream address: %s", trio_tcp_stream_addr)
        logger.debug("Socket address: %s", socket_addr)

        # Verify complete delegation chain
        assert (
            stream_addr
            == muxed_stream_addr
            == mplex_addr
            == secure_session_addr
            == raw_connection_addr
            == trio_tcp_stream_addr
            == socket_addr
        )

        # Convert to multiaddr and verify it matches host_b's cleaned address
        remote_address_multiaddr = _remote_address_to_multiaddr(stream_addr)
        host_b_addr = clean_multiaddr(host_b.get_addrs()[0])

        logger.debug("Remote address multiaddr: %s", remote_address_multiaddr)
        logger.debug("Host B cleaned address: %s", host_b_addr)

        assert remote_address_multiaddr == host_b_addr

        await stream.close()
