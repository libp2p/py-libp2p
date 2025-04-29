import logging

import pytest
import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.identity.identify.identify import (
    _mk_identify_protobuf,
)
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from libp2p.identity.identify_push.identify_push import (
    ID_PUSH,
    _update_peerstore_from_identify,
    identify_push_handler_for,
    push_identify_to_peer,
    push_identify_to_peers,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from tests.utils.factories import (
    host_pair_factory,
)

logger = logging.getLogger("libp2p.identity.identify-push-test")


@pytest.mark.trio
async def test_identify_push_protocol(security_protocol):
    """
    Test the basic functionality of the identify/push protocol.

    This test verifies that when host_a pushes identify information to host_b:
    1. The information is correctly received and processed
    2. The peerstore of host_b is updated with host_a's peer ID
    3. The peerstore contains all of host_a's addresses
    4. The peerstore contains all of host_a's supported protocols
    5. The public key in the peerstore matches host_a's public key
    """
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Set up the identify/push handlers
        host_b.set_stream_handler(ID_PUSH, identify_push_handler_for(host_b))

        # Push identify information from host_a to host_b
        await push_identify_to_peer(host_a, host_b.get_id())

        # Wait a bit for the push to complete
        await trio.sleep(0.1)

        # Get the peerstore from host_b
        peerstore = host_b.get_peerstore()

        # Check that host_b's peerstore has been updated with host_a's information
        peer_id = host_a.get_id()

        # Check that the peer is in the peerstore
        assert peer_id in peerstore.peer_ids()

        # Check that the addresses have been updated
        host_a_addrs = set(host_a.get_addrs())
        peerstore_addrs = set(peerstore.addrs(peer_id))

        # The peerstore might have additional addresses from the connection
        # So we just check that all of host_a's addresses are in the peerstore
        assert all(addr in peerstore_addrs for addr in host_a_addrs)

        # Check that the protocols have been updated
        host_a_protocols = set(host_a.get_mux().get_protocols())
        # Use get_protocols instead of protocols
        peerstore_protocols = set(peerstore.get_protocols(peer_id))

        # The peerstore might have additional protocols
        # So we just check that all of host_a's protocols are in the peerstore
        assert all(protocol in peerstore_protocols for protocol in host_a_protocols)

        # Check that the public key has been updated
        host_a_public_key = host_a.get_public_key().serialize()
        peerstore_public_key = peerstore.pubkey(peer_id).serialize()

        assert host_a_public_key == peerstore_public_key


@pytest.mark.trio
async def test_identify_push_handler(security_protocol):
    """
    Test the identify_push_handler_for function specifically.

    This test focuses on verifying that the handler function correctly:
    1. Receives the identify message
    2. Updates the peerstore with the peer information
    3. Processes all fields of the identify message (addresses, protocols, public key)

    Note: This test is similar to test_identify_push_protocol but specifically
    focuses on the handler function's behavior.
    """
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Set up the identify/push handlers
        host_b.set_stream_handler(ID_PUSH, identify_push_handler_for(host_b))

        # Push identify information from host_a to host_b
        await push_identify_to_peer(host_a, host_b.get_id())

        # Wait a bit for the push to complete
        await trio.sleep(0.1)

        # Get the peerstore from host_b
        peerstore = host_b.get_peerstore()

        # Check that host_b's peerstore has been updated with host_a's information
        peer_id = host_a.get_id()

        # Check that the peer is in the peerstore
        assert peer_id in peerstore.peer_ids()

        # Check that the addresses have been updated
        host_a_addrs = set(host_a.get_addrs())
        peerstore_addrs = set(peerstore.addrs(peer_id))

        # The peerstore might have additional addresses from the connection
        # So we just check that all of host_a's addresses are in the peerstore
        assert all(addr in peerstore_addrs for addr in host_a_addrs)

        # Check that the protocols have been updated
        host_a_protocols = set(host_a.get_mux().get_protocols())
        # Use get_protocols instead of protocols
        peerstore_protocols = set(peerstore.get_protocols(peer_id))

        # The peerstore might have additional protocols
        # So we just check that all of host_a's protocols are in the peerstore
        assert all(protocol in peerstore_protocols for protocol in host_a_protocols)

        # Check that the public key has been updated
        host_a_public_key = host_a.get_public_key().serialize()
        peerstore_public_key = peerstore.pubkey(peer_id).serialize()

        assert host_a_public_key == peerstore_public_key


@pytest.mark.trio
async def test_identify_push_to_peers(security_protocol):
    """
    Test the push_identify_to_peers function to broadcast identity to multiple peers.

    This test verifies that:
    1. Host_a can push identify information to multiple peers simultaneously
    2. The identify information is correctly received by all connected peers
    3. Both host_b and host_c have their peerstores updated with host_a's information

    This tests the broadcasting capability of the identify/push protocol.
    """
    # Create three hosts
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create a third host
        # Instead of using key_pair, create a new host directly

        # Create a new key pair for host_c
        key_pair_c = create_new_key_pair()
        host_c = new_host(key_pair=key_pair_c)

        # Set up the identify/push handlers
        host_b.set_stream_handler(ID_PUSH, identify_push_handler_for(host_b))
        host_c.set_stream_handler(ID_PUSH, identify_push_handler_for(host_c))

        # Start listening on a random port using the run context manager
        listen_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
        async with host_c.run([listen_addr]):
            # Connect host_c to host_a and host_b
            await host_c.connect(info_from_p2p_addr(host_a.get_addrs()[0]))
            await host_c.connect(info_from_p2p_addr(host_b.get_addrs()[0]))

            # Push identify information from host_a to all connected peers
            await push_identify_to_peers(host_a)

            # Wait a bit for the push to complete
            await trio.sleep(0.1)

            # Check that host_b's peerstore has been updated with host_a's information
            peerstore_b = host_b.get_peerstore()
            peer_id_a = host_a.get_id()

            # Check that the peer is in the peerstore
            assert peer_id_a in peerstore_b.peer_ids()

            # Check that host_c's peerstore has been updated with host_a's information
            peerstore_c = host_c.get_peerstore()

            # Check that the peer is in the peerstore
            assert peer_id_a in peerstore_c.peer_ids()


@pytest.mark.trio
async def test_push_identify_to_peers_with_explicit_params(security_protocol):
    """
    Test the push_identify_to_peers function with explicit parameters.

    This test verifies that:
    1. The function correctly handles an explicitly provided set of peer IDs
    2. The function correctly uses the provided observed_multiaddr
    3. The identify information is only pushed to the specified peers
    4. The observed address is correctly included in the identify message

    This test ensures all parameters of push_identify_to_peers are properly tested.
    """

    # Create four hosts to thoroughly test selective pushing
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create two additional hosts
        key_pair_c = create_new_key_pair()
        host_c = new_host(key_pair=key_pair_c)

        key_pair_d = create_new_key_pair()
        host_d = new_host(key_pair=key_pair_d)

        # Set up the identify/push handlers for all hosts
        host_b.set_stream_handler(ID_PUSH, identify_push_handler_for(host_b))
        host_c.set_stream_handler(ID_PUSH, identify_push_handler_for(host_c))
        host_d.set_stream_handler(ID_PUSH, identify_push_handler_for(host_d))

        # Start listening on random ports
        listen_addr_c = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
        listen_addr_d = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")

        async with host_c.run([listen_addr_c]), host_d.run([listen_addr_d]):
            # Connect all hosts to host_a
            await host_c.connect(info_from_p2p_addr(host_a.get_addrs()[0]))
            await host_d.connect(info_from_p2p_addr(host_a.get_addrs()[0]))

            # Create a specific observed multiaddr for the test
            observed_addr = multiaddr.Multiaddr("/ip4/192.0.2.1/tcp/1234")

            # Only push to hosts B and C (not D)
            selected_peers = {host_b.get_id(), host_c.get_id()}

            # Push identify information from host_a to selected peers with observed addr
            await push_identify_to_peers(
                host=host_a, peer_ids=selected_peers, observed_multiaddr=observed_addr
            )

            # Wait a bit for the push to complete
            await trio.sleep(0.1)

            # Check that host_b's and host_c's peerstores have been updated
            peerstore_b = host_b.get_peerstore()
            peerstore_c = host_c.get_peerstore()
            peerstore_d = host_d.get_peerstore()
            peer_id_a = host_a.get_id()

            # Hosts B and C should have peer_id_a in their peerstores
            assert peer_id_a in peerstore_b.peer_ids()
            assert peer_id_a in peerstore_c.peer_ids()

            # Host D should NOT have peer_id_a in its peerstore from the push
            # (it may still have it from the connection)
            # So we check for the observed address instead, which would only be
            # present from a push

            # Hosts B and C should have the observed address in their peerstores
            addrs_b = [str(addr) for addr in peerstore_b.addrs(peer_id_a)]
            addrs_c = [str(addr) for addr in peerstore_c.addrs(peer_id_a)]

            assert str(observed_addr) in addrs_b
            assert str(observed_addr) in addrs_c

            # If host D has addresses for peer_id_a, the observed address
            # should not be there
            if peer_id_a in peerstore_d.peer_ids():
                addrs_d = [str(addr) for addr in peerstore_d.addrs(peer_id_a)]
                assert str(observed_addr) not in addrs_d


@pytest.mark.trio
async def test_update_peerstore_from_identify(security_protocol):
    """
    Test the _update_peerstore_from_identify function directly.

    This test verifies that the internal function responsible for updating
    the peerstore from an identify message works correctly:
    1. It properly updates the peerstore with all fields from the identify message
    2. The peer ID is added to the peerstore
    3. All addresses are correctly stored
    4. All protocols are correctly stored
    5. The public key is correctly stored

    This tests the low-level peerstore update mechanism used by
    the identify/push protocol.
    """
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Get the peerstore from host_b
        peerstore = host_b.get_peerstore()

        # Create an identify message with host_a's information
        identify_msg = _mk_identify_protobuf(host_a, None)

        # Update the peerstore with the identify message
        await _update_peerstore_from_identify(peerstore, host_a.get_id(), identify_msg)

        # Check that the peerstore has been updated with host_a's information
        peer_id = host_a.get_id()

        # Check that the peer is in the peerstore
        assert peer_id in peerstore.peer_ids()

        # Check that the addresses have been updated
        host_a_addrs = set(host_a.get_addrs())
        peerstore_addrs = set(peerstore.addrs(peer_id))

        # The peerstore might have additional addresses from the connection
        # So we just check that all of host_a's addresses are in the peerstore
        assert all(addr in peerstore_addrs for addr in host_a_addrs)

        # Check that the protocols have been updated
        host_a_protocols = set(host_a.get_mux().get_protocols())
        # Use get_protocols instead of protocols
        peerstore_protocols = set(peerstore.get_protocols(peer_id))

        # The peerstore might have additional protocols
        # So we just check that all of host_a's protocols are in the peerstore
        assert all(protocol in peerstore_protocols for protocol in host_a_protocols)

        # Check that the public key has been updated
        host_a_public_key = host_a.get_public_key().serialize()
        peerstore_public_key = peerstore.pubkey(peer_id).serialize()

        assert host_a_public_key == peerstore_public_key


@pytest.mark.trio
async def test_partial_update_peerstore_from_identify(security_protocol):
    """
    Test partial updates of the peerstore using the identify/push protocol.

    This test verifies that:
    1. A partial identify message (containing only some fields) correctly updates
       the peerstore without affecting other existing information
    2. New protocols are added to the existing set in the peerstore
    3. The original protocols, addresses, and public key remain intact
    4. The update is additive rather than replacing all existing data

    This tests the ability of the identify/push protocol to handle incremental
    or partial updates to peer information.
    """
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Get the peerstore from host_b
        peerstore = host_b.get_peerstore()

        # First, update the peerstore with all of host_a's information
        identify_msg_full = _mk_identify_protobuf(host_a, None)
        await _update_peerstore_from_identify(
            peerstore, host_a.get_id(), identify_msg_full
        )

        # Now create a partial identify message with only some fields
        identify_msg_partial = Identify()

        # Only include the protocols field
        identify_msg_partial.protocols.extend(["new_protocol_1", "new_protocol_2"])

        # Update the peerstore with the partial identify message
        await _update_peerstore_from_identify(
            peerstore, host_a.get_id(), identify_msg_partial
        )

        # Check that the peerstore has been updated with the new protocols
        peer_id = host_a.get_id()

        # Check that the peer is still in the peerstore
        assert peer_id in peerstore.peer_ids()

        # Check that the new protocols have been added
        # Use get_protocols instead of protocols
        peerstore_protocols = set(peerstore.get_protocols(peer_id))

        # The new protocols should be in the peerstore
        assert "new_protocol_1" in peerstore_protocols
        assert "new_protocol_2" in peerstore_protocols

        # The original protocols should still be in the peerstore
        host_a_protocols = set(host_a.get_mux().get_protocols())
        assert all(protocol in peerstore_protocols for protocol in host_a_protocols)

        # The addresses should still be in the peerstore
        host_a_addrs = set(host_a.get_addrs())
        peerstore_addrs = set(peerstore.addrs(peer_id))
        assert all(addr in peerstore_addrs for addr in host_a_addrs)

        # The public key should still be in the peerstore
        host_a_public_key = host_a.get_public_key().serialize()
        peerstore_public_key = peerstore.pubkey(peer_id).serialize()
        assert host_a_public_key == peerstore_public_key
