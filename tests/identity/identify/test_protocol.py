import pytest

from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.identity.identify.protocol import ID, _mk_identify_protobuf
from libp2p.tools.factories import pair_of_connected_hosts


@pytest.mark.asyncio
async def test_identify_protocol():
    async with pair_of_connected_hosts() as (host_a, host_b):
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read()
        await stream.close()

        identify_response = Identify()
        identify_response.ParseFromString(response)
        assert identify_response == _mk_identify_protobuf(host_a)
