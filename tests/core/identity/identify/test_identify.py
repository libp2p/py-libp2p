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
    parse_identify_response,
)
from libp2p.peer.envelope import Envelope, consume_envelope, unmarshal_envelope
from libp2p.peer.peer_record import unmarshal_record
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
        # observed_addr represent host_b's address as observed by host_a
        # (i.e., the address from which host_b's request was received).
        stream = await host_b.new_stream(host_a.get_id(), (ID,))

        # Read the response (could be either format)
        # Read a larger chunk to get all the data before stream closes
        response = await stream.read(8192)  # Read enough data in one go

        await stream.close()

        # Parse the response (handles both old and new formats)
        identify_response = parse_identify_response(response)

        # Validate the recieved envelope and then store it in the certified-addr-book
        envelope, record = consume_envelope(
            identify_response.signedPeerRecord, "libp2p-peer-record"
        )
        assert host_b.peerstore.consume_peer_record(envelope, ttl=7200)

        # Check if the peer_id in the record is same as of host_a
        assert record.peer_id == host_a.get_id()

        # Check if the peer-record is correctly consumed
        assert host_a.get_addrs() == host_b.peerstore.addrs(host_a.get_id())
        assert isinstance(host_b.peerstore.get_peer_record(host_a.get_id()), Envelope)

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

        # The observed address should match the cleaned address
        assert Multiaddr(identify_response.observed_addr) == cleaned_addr

        # Check protocols
        assert set(identify_response.protocols) == set(host_a.get_mux().get_protocols())

        # sanity check if the peer_id of the identify msg are same
        assert (
            unmarshal_record(
                unmarshal_envelope(identify_response.signedPeerRecord).raw_payload
            ).peer_id
            == unmarshal_record(
                unmarshal_envelope(
                    _mk_identify_protobuf(host_a, cleaned_addr).signedPeerRecord
                ).raw_payload
            ).peer_id
        )
