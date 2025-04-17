import logging

import pytest
import trio

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
)
from tests.utils.factories import (
    host_pair_factory,
)

logger = logging.getLogger("libp2p.identity.identify-push-test")


@pytest.mark.trio
async def test_identify_push_protocol(security_protocol):
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
    # Create three hosts
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create a third host
        # Instead of using key_pair, create a new host directly
        import multiaddr

        from libp2p import (
            new_host,
        )
        from libp2p.crypto.secp256k1 import (
            create_new_key_pair,
        )
        from libp2p.peer.peerinfo import (
            info_from_p2p_addr,
        )

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
            from libp2p.identity.identify_push.identify_push import (
                push_identify_to_peers,
            )

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
async def test_update_peerstore_from_identify(security_protocol):
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
