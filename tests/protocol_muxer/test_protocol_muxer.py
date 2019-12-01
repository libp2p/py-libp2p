import pytest

from libp2p.host.exceptions import StreamFailure
from libp2p.tools.factories import HostFactory
from libp2p.tools.utils import create_echo_stream_handler


PROTOCOL_ECHO = "/echo/1.0.0"
PROTOCOL_POTATO = "/potato/1.0.0"
PROTOCOL_FOO = "/foo/1.0.0"
PROTOCOL_ROCK = "/rock/1.0.0"

ACK_PREFIX = "ack:"


async def perform_simple_test(
    expected_selected_protocol,
    protocols_for_client,
    protocols_with_handlers,
    is_host_secure,
):
    async with HostFactory.create_batch_and_listen(is_host_secure, 2) as hosts:
        for protocol in protocols_with_handlers:
            hosts[1].set_stream_handler(
                protocol, create_echo_stream_handler(ACK_PREFIX)
            )

        # Associate the peer with local ip address (see default parameters of Libp2p())
        hosts[0].get_peerstore().add_addrs(hosts[1].get_id(), hosts[1].get_addrs(), 10)
        stream = await hosts[0].new_stream(hosts[1].get_id(), protocols_for_client)
        messages = ["hello" + str(x) for x in range(10)]
        for message in messages:
            expected_resp = "ack:" + message
            await stream.write(message.encode())
            response = (await stream.read(len(expected_resp))).decode()
            assert response == expected_resp

        assert expected_selected_protocol == stream.get_protocol()


@pytest.mark.trio
async def test_single_protocol_succeeds(is_host_secure):
    expected_selected_protocol = PROTOCOL_ECHO
    await perform_simple_test(
        expected_selected_protocol,
        [expected_selected_protocol],
        [expected_selected_protocol],
        is_host_secure,
    )


@pytest.mark.trio
async def test_single_protocol_fails(is_host_secure):
    with pytest.raises(StreamFailure):
        await perform_simple_test(
            "", [PROTOCOL_ECHO], [PROTOCOL_POTATO], is_host_secure
        )

    # Cleanup not reached on error


@pytest.mark.trio
async def test_multiple_protocol_first_is_valid_succeeds(is_host_secure):
    expected_selected_protocol = PROTOCOL_ECHO
    protocols_for_client = [PROTOCOL_ECHO, PROTOCOL_POTATO]
    protocols_for_listener = [PROTOCOL_FOO, PROTOCOL_ECHO]
    await perform_simple_test(
        expected_selected_protocol,
        protocols_for_client,
        protocols_for_listener,
        is_host_secure,
    )


@pytest.mark.trio
async def test_multiple_protocol_second_is_valid_succeeds(is_host_secure):
    expected_selected_protocol = PROTOCOL_FOO
    protocols_for_client = [PROTOCOL_ROCK, PROTOCOL_FOO]
    protocols_for_listener = [PROTOCOL_FOO, PROTOCOL_ECHO]
    await perform_simple_test(
        expected_selected_protocol,
        protocols_for_client,
        protocols_for_listener,
        is_host_secure,
    )


@pytest.mark.trio
async def test_multiple_protocol_fails(is_host_secure):
    protocols_for_client = [PROTOCOL_ROCK, PROTOCOL_FOO, "/bar/1.0.0"]
    protocols_for_listener = ["/aspyn/1.0.0", "/rob/1.0.0", "/zx/1.0.0", "/alex/1.0.0"]
    with pytest.raises(StreamFailure):
        await perform_simple_test(
            "", protocols_for_client, protocols_for_listener, is_host_secure
        )
