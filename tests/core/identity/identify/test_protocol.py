import pytest

from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from libp2p.identity.identify.protocol import (
    AGENT_VERSION,
    ID,
    PROTOCOL_VERSION,
    _mk_identify_protobuf,
    _multiaddr_to_bytes,
)
from tests.factories import (
    host_pair_factory,
)


@pytest.mark.trio
async def test_identify_protocol(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read()
        await stream.close()

        identify_response = Identify()
        identify_response.ParseFromString(response)

        # sanity check
        assert identify_response == _mk_identify_protobuf(host_a)

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

        # TODO: Check observed address
        # assert identify_response.observed_addr == host_b.get_addrs()[0]

        # Check protocols
        assert set(identify_response.protocols) == set(host_a.get_mux().get_protocols())
