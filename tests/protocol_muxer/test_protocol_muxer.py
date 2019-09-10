import pytest

from libp2p.protocol_muxer.exceptions import MultiselectClientError
from tests.utils import echo_stream_handler, set_up_nodes_by_transport_opt

# TODO: Add tests for multiple streams being opened on different
# protocols through the same connection

# Note: async issues occurred when using the same port
# so that's why I use different ports here.
# TODO: modify tests so that those async issues don't occur
# when using the same ports across tests


async def perform_simple_test(
    expected_selected_protocol, protocols_for_client, protocols_with_handlers
):
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    for protocol in protocols_with_handlers:
        node_b.set_stream_handler(protocol, echo_stream_handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)

    stream = await node_a.new_stream(node_b.get_id(), protocols_for_client)
    messages = ["hello" + str(x) for x in range(10)]
    for message in messages:
        expected_resp = "ack:" + message
        await stream.write(message.encode())
        response = (await stream.read(len(expected_resp))).decode()
        assert response == expected_resp

    assert expected_selected_protocol == stream.get_protocol()

    # Success, terminate pending tasks.


@pytest.mark.asyncio
async def test_single_protocol_succeeds():
    expected_selected_protocol = "/echo/1.0.0"
    await perform_simple_test(
        expected_selected_protocol, ["/echo/1.0.0"], ["/echo/1.0.0"]
    )


@pytest.mark.asyncio
async def test_single_protocol_fails():
    with pytest.raises(MultiselectClientError):
        await perform_simple_test("", ["/echo/1.0.0"], ["/potato/1.0.0"])

    # Cleanup not reached on error


@pytest.mark.asyncio
async def test_multiple_protocol_first_is_valid_succeeds():
    expected_selected_protocol = "/echo/1.0.0"
    protocols_for_client = ["/echo/1.0.0", "/potato/1.0.0"]
    protocols_for_listener = ["/foo/1.0.0", "/echo/1.0.0"]
    await perform_simple_test(
        expected_selected_protocol, protocols_for_client, protocols_for_listener
    )


@pytest.mark.asyncio
async def test_multiple_protocol_second_is_valid_succeeds():
    expected_selected_protocol = "/foo/1.0.0"
    protocols_for_client = ["/rock/1.0.0", "/foo/1.0.0"]
    protocols_for_listener = ["/foo/1.0.0", "/echo/1.0.0"]
    await perform_simple_test(
        expected_selected_protocol, protocols_for_client, protocols_for_listener
    )


@pytest.mark.asyncio
async def test_multiple_protocol_fails():
    protocols_for_client = ["/rock/1.0.0", "/foo/1.0.0", "/bar/1.0.0"]
    protocols_for_listener = ["/aspyn/1.0.0", "/rob/1.0.0", "/zx/1.0.0", "/alex/1.0.0"]
    with pytest.raises(MultiselectClientError):
        await perform_simple_test("", protocols_for_client, protocols_for_listener)

    # Cleanup not reached on error
