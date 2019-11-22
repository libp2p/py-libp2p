import asyncio

import pytest

from libp2p import new_node
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.security.insecure.transport import InsecureSession, InsecureTransport
from libp2p.tools.constants import LISTEN_MADDR
from libp2p.tools.utils import connect

# TODO: Add tests for multiple streams being opened on different
# protocols through the same connection


def peer_id_for_node(node):
    return node.get_id()


initiator_key_pair = create_new_key_pair()

noninitiator_key_pair = create_new_key_pair()


async def perform_simple_test(
    assertion_func, transports_for_initiator, transports_for_noninitiator
):

    # Create libp2p nodes and connect them, then secure the connection, then check
    # the proper security was chosen
    # TODO: implement -- note we need to introduce the notion of communicating over a raw connection
    # for testing, we do NOT want to communicate over a stream so we can't just create two nodes
    # and use their conn because our mplex will internally relay messages to a stream

    node1 = await new_node(
        key_pair=initiator_key_pair, sec_opt=transports_for_initiator
    )
    node2 = await new_node(
        key_pair=noninitiator_key_pair, sec_opt=transports_for_noninitiator
    )

    await node1.get_network().listen(LISTEN_MADDR)
    await node2.get_network().listen(LISTEN_MADDR)

    await connect(node1, node2)

    # Wait a very short period to allow conns to be stored (since the functions
    # storing the conns are async, they may happen at slightly different times
    # on each node)
    await asyncio.sleep(0.1)

    # Get conns
    node1_conn = node1.get_network().connections[peer_id_for_node(node2)]
    node2_conn = node2.get_network().connections[peer_id_for_node(node1)]

    # Perform assertion
    assertion_func(node1_conn.muxed_conn.secured_conn)
    assertion_func(node2_conn.muxed_conn.secured_conn)

    # Success, terminate pending tasks.


@pytest.mark.asyncio
async def test_single_insecure_security_transport_succeeds():
    transports_for_initiator = {"foo": InsecureTransport(initiator_key_pair)}
    transports_for_noninitiator = {"foo": InsecureTransport(noninitiator_key_pair)}

    def assertion_func(conn):
        assert isinstance(conn, InsecureSession)

    await perform_simple_test(
        assertion_func, transports_for_initiator, transports_for_noninitiator
    )


@pytest.mark.asyncio
async def test_default_insecure_security():
    transports_for_initiator = None
    transports_for_noninitiator = None

    conn1 = None
    conn2 = None

    def assertion_func(conn):
        nonlocal conn1
        nonlocal conn2
        if not conn1:
            conn1 = conn
        elif not conn2:
            conn2 = conn
        else:
            assert conn1 == conn2

    await perform_simple_test(
        assertion_func, transports_for_initiator, transports_for_noninitiator
    )
