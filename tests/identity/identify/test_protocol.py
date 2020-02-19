import pytest

from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.identity.identify.protocol import ID, _mk_identify_protobuf
from libp2p.tools.factories import host_pair_factory


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
        assert identify_response == _mk_identify_protobuf(host_a)
