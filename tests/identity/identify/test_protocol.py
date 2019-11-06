import pytest

from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.identity.identify.protocol import ID, _mk_identify_protobuf
from libp2p.peer.peerinfo import info_from_p2p_addr
from tests.utils import set_up_nodes_by_transport_opt


@pytest.mark.asyncio
async def test_identify_protocol():
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (host_a, host_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    addr = host_a.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await host_b.connect(info)

    stream = await host_b.new_stream(host_a.get_id(), (ID,))
    response = await stream.read()
    await stream.close()

    identify_response = Identify()
    identify_response.ParseFromString(response)
    assert identify_response == _mk_identify_protobuf(host_a)
