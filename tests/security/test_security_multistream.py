import pytest

from tests.utils import cleanup, set_up_nodes_by_transport_opt
from libp2p.security.security_multistream import SecurityMultistream
from tests.security.insecure_multistream import InsecureConn, InsecureTransport

# TODO: Add tests for multiple streams being opened on different
# protocols through the same connection


async def perform_simple_test(assertion_func, transports_for_initiator, transports_for_noninitiator):
    
    # Create libp2p nodes and connect them, then secure the connection, then check
    # the proper security was chosen
    # TODO: implement -- note we need to introduce the notion of communicating over a raw connection
    # for testing, we do NOT want to communicate over a stream so we can't just create two nodes
    # and use their conn because our mplex will internally relay messages to a stream
    conn = []

    # Fill initiator
    sec_multi_initiator = SecurityMultistream()
    for i, transport in enumerate(transports_for_initiator):
        sec_multi_initiator.add_transport(str(i), transport)

    # Fill non-initiator
    sec_multi_noninitiator = SecurityMultistream()
    for i, transport in enumerate(transports_for_noninitiator):
        sec_multi_noninitiator.add_transport(str(i), transport)

    # Perform negotiation
    tasks = []
    tasks.append(asyncio.ensure_future(sec_multi_initiator.secure_inbound(conn)))
    tasks.append(asyncio.ensure_future(sec_multi_noninitiator.secure_inbound(conn)))
    secured_conns = await asyncio.gather(*tasks)

    # Perform assertion
    for conn in secured_conns:
        assertion_func(conn.get_security_details())

    # Success, terminate pending tasks.
    await cleanup()


@pytest.mark.asyncio
async def test_single_protocol_succeeds():
    expected_selected_protocol = "/echo/1.0.0"
    await perform_simple_test(expected_selected_protocol,
                              ["/echo/1.0.0"], ["/echo/1.0.0"])


@pytest.mark.asyncio
async def test_single_protocol_fails():
    with pytest.raises(MultiselectClientError):
        await perform_simple_test("", ["/echo/1.0.0"],
                                  ["/potato/1.0.0"])

    # Cleanup not reached on error
    await cleanup()


@pytest.mark.asyncio
async def test_multiple_protocol_first_is_valid_succeeds():
    expected_selected_protocol = "/echo/1.0.0"
    protocols_for_client = ["/echo/1.0.0", "/potato/1.0.0"]
    protocols_for_listener = ["/foo/1.0.0", "/echo/1.0.0"]
    await perform_simple_test(expected_selected_protocol, protocols_for_client,
                              protocols_for_listener)


@pytest.mark.asyncio
async def test_multiple_protocol_second_is_valid_succeeds():
    expected_selected_protocol = "/foo/1.0.0"
    protocols_for_client = ["/rock/1.0.0", "/foo/1.0.0"]
    protocols_for_listener = ["/foo/1.0.0", "/echo/1.0.0"]
    await perform_simple_test(expected_selected_protocol, protocols_for_client,
                              protocols_for_listener)


@pytest.mark.asyncio
async def test_multiple_protocol_fails():
    protocols_for_client = ["/rock/1.0.0", "/foo/1.0.0", "/bar/1.0.0"]
    protocols_for_listener = ["/aspyn/1.0.0", "/rob/1.0.0", "/zx/1.0.0", "/alex/1.0.0"]
    with pytest.raises(MultiselectClientError):
        await perform_simple_test("", protocols_for_client,
                                  protocols_for_listener)

    # Cleanup not reached on error
    await cleanup()
