import pytest
import multiaddr

from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.exceptions import (
    StreamError,
)
from libp2p.tools.constants import (
    MAX_READ_LEN,
)
from libp2p.tools.utils import (
    connect,
    create_echo_stream_handler,
)
from tests.utils.factories import (
    HostFactory,
)

PROTOCOL_ID_0 = TProtocol("/echo/0")
PROTOCOL_ID_1 = TProtocol("/echo/1")
PROTOCOL_ID_2 = TProtocol("/echo/2")
PROTOCOL_ID_3 = TProtocol("/echo/3")

ACK_STR_0 = "ack_0:"
ACK_STR_1 = "ack_1:"
ACK_STR_2 = "ack_2:"
ACK_STR_3 = "ack_3:"


@pytest.mark.trio
async def test_simple_messages(security_protocol):
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        hosts[1].set_stream_handler(
            PROTOCOL_ID_0, create_echo_stream_handler(ACK_STR_0)
        )

        # Associate the peer with local ip address (see default parameters of Libp2p())
        hosts[0].get_peerstore().add_addrs(hosts[1].get_id(), hosts[1].get_addrs(), 10)

        stream = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_0])

        messages = ["hello" + str(x) for x in range(10)]
        for message in messages:
            await stream.write(message.encode())
            response = (await stream.read(MAX_READ_LEN)).decode()
            assert response == (ACK_STR_0 + message)


@pytest.mark.trio
async def test_double_response(security_protocol):
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:

        async def double_response_stream_handler(stream):
            while True:
                try:
                    read_string = (await stream.read(MAX_READ_LEN)).decode()
                except StreamError:
                    break

                response = ACK_STR_0 + read_string
                try:
                    await stream.write(response.encode())
                except StreamError:
                    break

                response = ACK_STR_1 + read_string
                try:
                    await stream.write(response.encode())
                except StreamError:
                    break

        hosts[1].set_stream_handler(PROTOCOL_ID_0, double_response_stream_handler)

        # Associate the peer with local ip address (see default parameters of Libp2p())
        hosts[0].get_peerstore().add_addrs(hosts[1].get_id(), hosts[1].get_addrs(), 10)
        stream = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_0])

        messages = ["hello" + str(x) for x in range(10)]
        for message in messages:
            await stream.write(message.encode())

            response1 = (await stream.read(MAX_READ_LEN)).decode()
            assert response1 == (ACK_STR_0 + message)

            response2 = (await stream.read(MAX_READ_LEN)).decode()
            assert response2 == (ACK_STR_1 + message)


@pytest.mark.trio
async def test_multiple_streams(security_protocol):
    # hosts[0] should be able to open a stream with hosts[1] and then vice versa.
    # Stream IDs should be generated uniquely so that the stream state is not
    # overwritten

    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        hosts[0].set_stream_handler(
            PROTOCOL_ID_0, create_echo_stream_handler(ACK_STR_0)
        )
        hosts[1].set_stream_handler(
            PROTOCOL_ID_1, create_echo_stream_handler(ACK_STR_1)
        )

        # Associate the peer with local ip address (see default parameters of Libp2p())
        hosts[0].get_peerstore().add_addrs(hosts[1].get_id(), hosts[1].get_addrs(), 10)
        hosts[1].get_peerstore().add_addrs(hosts[0].get_id(), hosts[0].get_addrs(), 10)

        stream_a = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_1])
        stream_b = await hosts[1].new_stream(hosts[0].get_id(), [PROTOCOL_ID_0])

        # A writes to /echo_b via stream_a, and B writes to /echo_a via stream_b
        messages = ["hello" + str(x) for x in range(10)]
        for message in messages:
            a_message = message + "_a"
            b_message = message + "_b"

            await stream_a.write(a_message.encode())
            await stream_b.write(b_message.encode())

            response_a = (await stream_a.read(MAX_READ_LEN)).decode()
            response_b = (await stream_b.read(MAX_READ_LEN)).decode()

            assert response_a == (ACK_STR_1 + a_message) and response_b == (
                ACK_STR_0 + b_message
            )


@pytest.mark.trio
async def test_multiple_streams_same_initiator_different_protocols(security_protocol):
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        hosts[1].set_stream_handler(
            PROTOCOL_ID_0, create_echo_stream_handler(ACK_STR_0)
        )
        hosts[1].set_stream_handler(
            PROTOCOL_ID_1, create_echo_stream_handler(ACK_STR_1)
        )
        hosts[1].set_stream_handler(
            PROTOCOL_ID_2, create_echo_stream_handler(ACK_STR_2)
        )

        # Associate the peer with local ip address (see default parameters of Libp2p())
        hosts[0].get_peerstore().add_addrs(hosts[1].get_id(), hosts[1].get_addrs(), 10)
        hosts[1].get_peerstore().add_addrs(hosts[0].get_id(), hosts[0].get_addrs(), 10)

        # Open streams to hosts[1] over echo_a1 echo_a2 echo_a3 protocols
        stream_a1 = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_0])
        stream_a2 = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_1])
        stream_a3 = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_2])

        messages = ["hello" + str(x) for x in range(10)]
        for message in messages:
            a1_message = message + "_a1"
            a2_message = message + "_a2"
            a3_message = message + "_a3"

            await stream_a1.write(a1_message.encode())
            await stream_a2.write(a2_message.encode())
            await stream_a3.write(a3_message.encode())

            response_a1 = (await stream_a1.read(MAX_READ_LEN)).decode()
            response_a2 = (await stream_a2.read(MAX_READ_LEN)).decode()
            response_a3 = (await stream_a3.read(MAX_READ_LEN)).decode()

            assert (
                response_a1 == (ACK_STR_0 + a1_message)
                and response_a2 == (ACK_STR_1 + a2_message)
                and response_a3 == (ACK_STR_2 + a3_message)
            )

        # Success, terminate pending tasks.


@pytest.mark.trio
async def test_multiple_streams_two_initiators(security_protocol):
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        hosts[0].set_stream_handler(
            PROTOCOL_ID_2, create_echo_stream_handler(ACK_STR_2)
        )
        hosts[0].set_stream_handler(
            PROTOCOL_ID_3, create_echo_stream_handler(ACK_STR_3)
        )

        hosts[1].set_stream_handler(
            PROTOCOL_ID_0, create_echo_stream_handler(ACK_STR_0)
        )
        hosts[1].set_stream_handler(
            PROTOCOL_ID_1, create_echo_stream_handler(ACK_STR_1)
        )

        # Associate the peer with local ip address (see default parameters of Libp2p())
        hosts[0].get_peerstore().add_addrs(hosts[1].get_id(), hosts[1].get_addrs(), 10)
        hosts[1].get_peerstore().add_addrs(hosts[0].get_id(), hosts[0].get_addrs(), 10)

        stream_a1 = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_0])
        stream_a2 = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_1])

        stream_b1 = await hosts[1].new_stream(hosts[0].get_id(), [PROTOCOL_ID_2])
        stream_b2 = await hosts[1].new_stream(hosts[0].get_id(), [PROTOCOL_ID_3])

        # A writes to /echo_b via stream_a, and B writes to /echo_a via stream_b
        messages = ["hello" + str(x) for x in range(10)]
        for message in messages:
            a1_message = message + "_a1"
            a2_message = message + "_a2"

            b1_message = message + "_b1"
            b2_message = message + "_b2"

            await stream_a1.write(a1_message.encode())
            await stream_a2.write(a2_message.encode())

            await stream_b1.write(b1_message.encode())
            await stream_b2.write(b2_message.encode())

            response_a1 = (await stream_a1.read(MAX_READ_LEN)).decode()
            response_a2 = (await stream_a2.read(MAX_READ_LEN)).decode()

            response_b1 = (await stream_b1.read(MAX_READ_LEN)).decode()
            response_b2 = (await stream_b2.read(MAX_READ_LEN)).decode()

            assert (
                response_a1 == (ACK_STR_0 + a1_message)
                and response_a2 == (ACK_STR_1 + a2_message)
                and response_b1 == (ACK_STR_2 + b1_message)
                and response_b2 == (ACK_STR_3 + b2_message)
            )


@pytest.mark.trio
async def test_triangle_nodes_connection(security_protocol):
    async with HostFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as hosts:
        hosts[0].set_stream_handler(
            PROTOCOL_ID_0, create_echo_stream_handler(ACK_STR_0)
        )
        hosts[1].set_stream_handler(
            PROTOCOL_ID_0, create_echo_stream_handler(ACK_STR_0)
        )
        hosts[2].set_stream_handler(
            PROTOCOL_ID_0, create_echo_stream_handler(ACK_STR_0)
        )

        # Associate the peer with local ip address (see default parameters of Libp2p())
        # Associate all permutations
        hosts[0].get_peerstore().add_addrs(hosts[1].get_id(), hosts[1].get_addrs(), 10)
        hosts[0].get_peerstore().add_addrs(hosts[2].get_id(), hosts[2].get_addrs(), 10)

        hosts[1].get_peerstore().add_addrs(hosts[0].get_id(), hosts[0].get_addrs(), 10)
        hosts[1].get_peerstore().add_addrs(hosts[2].get_id(), hosts[2].get_addrs(), 10)

        hosts[2].get_peerstore().add_addrs(hosts[0].get_id(), hosts[0].get_addrs(), 10)
        hosts[2].get_peerstore().add_addrs(hosts[1].get_id(), hosts[1].get_addrs(), 10)

        stream_0_to_1 = await hosts[0].new_stream(hosts[1].get_id(), [PROTOCOL_ID_0])
        stream_0_to_2 = await hosts[0].new_stream(hosts[2].get_id(), [PROTOCOL_ID_0])

        stream_1_to_0 = await hosts[1].new_stream(hosts[0].get_id(), [PROTOCOL_ID_0])
        stream_1_to_2 = await hosts[1].new_stream(hosts[2].get_id(), [PROTOCOL_ID_0])

        stream_2_to_0 = await hosts[2].new_stream(hosts[0].get_id(), [PROTOCOL_ID_0])
        stream_2_to_1 = await hosts[2].new_stream(hosts[1].get_id(), [PROTOCOL_ID_0])

        messages = ["hello" + str(x) for x in range(5)]
        streams = [
            stream_0_to_1,
            stream_0_to_2,
            stream_1_to_0,
            stream_1_to_2,
            stream_2_to_0,
            stream_2_to_1,
        ]

        for message in messages:
            for stream in streams:
                await stream.write(message.encode())
                response = (await stream.read(MAX_READ_LEN)).decode()
                assert response == (ACK_STR_0 + message)


@pytest.mark.trio
async def test_host_connect(security_protocol):
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        assert len(hosts[0].get_peerstore().peer_ids()) == 1

        await connect(hosts[0], hosts[1])
        assert len(hosts[0].get_peerstore().peer_ids()) == 2

        await connect(hosts[0], hosts[1])
        # make sure we don't do double connection
        assert len(hosts[0].get_peerstore().peer_ids()) == 2

        assert hosts[1].get_id() in hosts[0].get_peerstore().peer_ids()
        ma_node_b = multiaddr.Multiaddr("/p2p/%s" % hosts[1].get_id().pretty())
        for addr in hosts[0].get_peerstore().addrs(hosts[1].get_id()):
            assert addr.encapsulate(ma_node_b) in hosts[1].get_addrs()
