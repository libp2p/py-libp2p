import logging

import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.identity.identify.identify import (
    AGENT_VERSION,
    ID,
    PROTOCOL_VERSION,
    _mk_identify_protobuf,
    _multiaddr_to_bytes,
)
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from tests.utils.factories import (
    host_pair_factory,
)

logger = logging.getLogger("libp2p.identity.identify-test")


@pytest.mark.trio
async def test_identify_protocol(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Here, host_b is the requester and host_a is the responder.
        # observed_addr represent host_b’s address as observed by host_a
        # (i.e., the address from which host_b’s request was received).
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
        host_b_addr = host_b.get_addrs()[0]
        host_b_peer_id = host_b.get_id()
        cleaned_addr = host_b_addr.decapsulate(Multiaddr(f"/p2p/{host_b_peer_id}"))

        logger.debug("observed_addr: %s", Multiaddr(identify_response.observed_addr))
        logger.debug("host_b.get_addrs()[0]: %s", host_b.get_addrs()[0])
        logger.debug("cleaned_addr= %s", cleaned_addr)
        assert identify_response.observed_addr == _multiaddr_to_bytes(cleaned_addr)

        # Check protocols
        assert set(identify_response.protocols) == set(host_a.get_mux().get_protocols())

        # sanity check
        assert identify_response == _mk_identify_protobuf(host_a, cleaned_addr)
