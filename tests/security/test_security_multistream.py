import asyncio
import multiaddr
import pytest

from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.protocol_muxer.multiselect_client import MultiselectClientError
from libp2p.security.insecure_security import InsecureTransport
from libp2p.security.simple_security import SimpleSecurityTransport
from tests.utils import cleanup

# TODO: Add tests for multiple streams being opened on different
# protocols through the same connection


def peer_id_for_node(node):
    addr = node.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    return info.peer_id


async def connect(node1, node2):
    """
    Connect node1 to node2
    """
    addr = node2.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node1.connect(info)


async def perform_simple_test(
    assertion_func, transports_for_initiator, transports_for_noninitiator
):

    # Create libp2p nodes and connect them, then secure the connection, then check
    # the proper security was chosen
    # TODO: implement -- note we need to introduce the notion of communicating over a raw connection
    # for testing, we do NOT want to communicate over a stream so we can't just create two nodes
    # and use their conn because our mplex will internally relay messages to a stream
    sec_opt1 = transports_for_initiator
    sec_opt2 = transports_for_noninitiator

    node1 = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"], sec_opt=sec_opt1)
    node2 = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"], sec_opt=sec_opt2)

    await node1.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))
    await node2.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))

    await connect(node1, node2)

    # Wait a very short period to allow conns to be stored (since the functions
    # storing the conns are async, they may happen at slightly different times
    # on each node)
    await asyncio.sleep(0.1)

    # Get conns
    node1_conn = node1.get_network().connections[peer_id_for_node(node2)]
    node2_conn = node2.get_network().connections[peer_id_for_node(node1)]

    # Perform assertion
    assertion_func(node1_conn.secured_conn.get_security_details())
    assertion_func(node2_conn.secured_conn.get_security_details())

    # Success, terminate pending tasks.
    await cleanup()


@pytest.mark.asyncio
async def test_single_insecure_security_transport_succeeds():
    transports_for_initiator = {"foo": InsecureTransport("foo")}
    transports_for_noninitiator = {"foo": InsecureTransport("foo")}

    def assertion_func(details):
        assert details["id"] == "foo"

    await perform_simple_test(
        assertion_func, transports_for_initiator, transports_for_noninitiator
    )


@pytest.mark.asyncio
async def test_single_simple_test_security_transport_succeeds():
    transports_for_initiator = {"tacos": SimpleSecurityTransport("tacos")}
    transports_for_noninitiator = {"tacos": SimpleSecurityTransport("tacos")}

    def assertion_func(details):
        assert details["key_phrase"] == "tacos"

    await perform_simple_test(
        assertion_func, transports_for_initiator, transports_for_noninitiator
    )


@pytest.mark.asyncio
async def test_two_simple_test_security_transport_for_initiator_succeeds():
    transports_for_initiator = {
        "tacos": SimpleSecurityTransport("tacos"),
        "shleep": SimpleSecurityTransport("shleep"),
    }
    transports_for_noninitiator = {"shleep": SimpleSecurityTransport("shleep")}

    def assertion_func(details):
        assert details["key_phrase"] == "shleep"

    await perform_simple_test(
        assertion_func, transports_for_initiator, transports_for_noninitiator
    )


@pytest.mark.asyncio
async def test_two_simple_test_security_transport_for_noninitiator_succeeds():
    transports_for_initiator = {"tacos": SimpleSecurityTransport("tacos")}
    transports_for_noninitiator = {
        "shleep": SimpleSecurityTransport("shleep"),
        "tacos": SimpleSecurityTransport("tacos"),
    }

    def assertion_func(details):
        assert details["key_phrase"] == "tacos"

    await perform_simple_test(
        assertion_func, transports_for_initiator, transports_for_noninitiator
    )


@pytest.mark.asyncio
async def test_two_simple_test_security_transport_for_both_succeeds():
    transports_for_initiator = {
        "a": SimpleSecurityTransport("a"),
        "b": SimpleSecurityTransport("b"),
    }
    transports_for_noninitiator = {
        "c": SimpleSecurityTransport("c"),
        "b": SimpleSecurityTransport("b"),
    }

    def assertion_func(details):
        assert details["key_phrase"] == "b"

    await perform_simple_test(
        assertion_func, transports_for_initiator, transports_for_noninitiator
    )


@pytest.mark.asyncio
async def test_multiple_security_none_the_same_fails():
    transports_for_initiator = {
        "a": SimpleSecurityTransport("a"),
        "b": SimpleSecurityTransport("b"),
    }
    transports_for_noninitiator = {
        "c": SimpleSecurityTransport("c"),
        "d": SimpleSecurityTransport("d"),
    }

    def assertion_func(_):
        assert False

    with pytest.raises(MultiselectClientError):
        await perform_simple_test(
            assertion_func, transports_for_initiator, transports_for_noninitiator
        )

    await cleanup()


@pytest.mark.asyncio
async def test_default_insecure_security():
    transports_for_initiator = None
    transports_for_noninitiator = None

    details1 = None
    details2 = None

    def assertion_func(details):
        nonlocal details1
        nonlocal details2
        if not details1:
            details1 = details
        elif not details2:
            details2 = details
        else:
            assert details1 == details2

    await perform_simple_test(
        assertion_func, transports_for_initiator, transports_for_noninitiator
    )
