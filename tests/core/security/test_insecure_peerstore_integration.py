import pytest
import trio
from trio.testing import memory_stream_pair

from libp2p.abc import IRawConnection
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.peer.peerdata import PeerData
from libp2p.peer.peerstore import PeerStore
from libp2p.security.exceptions import HandshakeFailure
from libp2p.security.insecure.transport import InsecureTransport


# Adapter class to bridge between trio streams and libp2p raw connections
class TrioStreamAdapter(IRawConnection):
    def __init__(self, send_stream, receive_stream, is_initiator: bool = False):
        self.send_stream = send_stream
        self.receive_stream = receive_stream
        self.is_initiator = is_initiator

    async def write(self, data: bytes) -> None:
        await self.send_stream.send_all(data)

    async def read(self, n: int | None = None) -> bytes:
        if n is None or n == -1:
            raise ValueError("Reading unbounded not supported")
        return await self.receive_stream.receive_some(n)

    async def close(self) -> None:
        await self.send_stream.aclose()
        await self.receive_stream.aclose()

    def get_remote_address(self) -> tuple[str, int] | None:
        # Return None since this is a test adapter without real network info
        return None


@pytest.mark.trio
async def test_insecure_transport_stores_pubkey_in_peerstore():
    """
    Test that InsecureTransport stores the pubkey and peerid in
    peerstore during handshake.
    """
    # Create key pairs for both sides
    local_key_pair = create_new_key_pair()
    remote_key_pair = create_new_key_pair()

    # Create peer IDs
    remote_peer_id = ID.from_pubkey(remote_key_pair.public_key)

    # Create peerstore
    peerstore = PeerStore()

    # Create memory streams for communication
    local_send, remote_receive = memory_stream_pair()
    remote_send, local_receive = memory_stream_pair()

    # Create adapters
    local_stream = TrioStreamAdapter(local_send, local_receive, is_initiator=True)
    remote_stream = TrioStreamAdapter(remote_send, remote_receive, is_initiator=False)

    # Create transports
    local_transport = InsecureTransport(local_key_pair, peerstore=peerstore)
    remote_transport = InsecureTransport(remote_key_pair, peerstore=None)

    # Run handshake
    async def run_local_handshake(nursery_results):
        with trio.move_on_after(5):
            local_conn = await local_transport.secure_outbound(
                local_stream, remote_peer_id
            )
            nursery_results["local"] = local_conn

    async def run_remote_handshake(nursery_results):
        with trio.move_on_after(5):
            remote_conn = await remote_transport.secure_inbound(remote_stream)
            nursery_results["remote"] = remote_conn

    nursery_results = {}
    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_local_handshake, nursery_results)
        nursery.start_soon(run_remote_handshake, nursery_results)
        await trio.sleep(0.1)  # Give tasks a chance to finish

    local_conn = nursery_results.get("local")
    remote_conn = nursery_results.get("remote")

    assert local_conn is not None, "Local handshake failed"
    assert remote_conn is not None, "Remote handshake failed"

    # Verify that the remote peer ID is in the peerstore
    assert remote_peer_id in peerstore.peer_ids()

    # Verify that the public key was stored and matches
    stored_pubkey = peerstore.pubkey(remote_peer_id)
    assert stored_pubkey is not None
    assert stored_pubkey.serialize() == remote_key_pair.public_key.serialize()


@pytest.mark.trio
async def test_insecure_transport_without_peerstore():
    """
    Test that InsecureTransport works correctly
    without a peerstore.
    """
    # Create key pairs for both sides
    local_key_pair = create_new_key_pair()
    remote_key_pair = create_new_key_pair()

    # Create peer IDs
    remote_peer_id = ID.from_pubkey(remote_key_pair.public_key)

    # Create memory streams for communication
    local_send, remote_receive = memory_stream_pair()
    remote_send, local_receive = memory_stream_pair()

    # Create adapters
    local_stream = TrioStreamAdapter(local_send, local_receive, is_initiator=True)
    remote_stream = TrioStreamAdapter(remote_send, remote_receive, is_initiator=False)

    # Create transports without peerstore
    local_transport = InsecureTransport(local_key_pair, peerstore=None)
    remote_transport = InsecureTransport(remote_key_pair, peerstore=None)

    # Run handshake
    async def run_local_handshake(nursery_results):
        with trio.move_on_after(5):
            local_conn = await local_transport.secure_outbound(
                local_stream, remote_peer_id
            )
            nursery_results["local"] = local_conn

    async def run_remote_handshake(nursery_results):
        with trio.move_on_after(5):
            remote_conn = await remote_transport.secure_inbound(remote_stream)
            nursery_results["remote"] = remote_conn

    nursery_results = {}
    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_local_handshake, nursery_results)
        nursery.start_soon(run_remote_handshake, nursery_results)
        await trio.sleep(0.1)  # Give tasks a chance to finish

    local_conn = nursery_results.get("local")
    remote_conn = nursery_results.get("remote")

    # Verify that handshake still works without a peerstore
    assert local_conn is not None, "Local handshake failed"
    assert remote_conn is not None, "Remote handshake failed"


@pytest.mark.trio
async def test_peerstore_unchanged_when_handshake_fails():
    """
    Test that the peerstore remains unchanged if the handshake fails
    due to a peer ID mismatch.
    """
    # Create key pairs for both sides
    local_key_pair = create_new_key_pair()
    remote_key_pair = create_new_key_pair()

    # Create a third key pair to cause a mismatch
    mismatch_key_pair = create_new_key_pair()

    # Create peer IDs
    remote_peer_id = ID.from_pubkey(remote_key_pair.public_key)
    mismatch_peer_id = ID.from_pubkey(mismatch_key_pair.public_key)

    # Create peerstore and add some initial data to verify it stays unchanged
    peerstore = PeerStore()

    # Store some initial data in peerstore to verify it remains unchanged
    initial_key_pair = create_new_key_pair()
    initial_peer_id = ID.from_pubkey(initial_key_pair.public_key)
    peerstore.add_pubkey(initial_peer_id, initial_key_pair.public_key)

    # Remember the initial state of the peerstore
    initial_peer_ids = set(peerstore.peer_ids())

    # Create memory streams for communication
    local_send, remote_receive = memory_stream_pair()
    remote_send, local_receive = memory_stream_pair()

    # Create adapters
    local_stream = TrioStreamAdapter(local_send, local_receive, is_initiator=True)
    remote_stream = TrioStreamAdapter(remote_send, remote_receive, is_initiator=False)

    # Create transports
    local_transport = InsecureTransport(local_key_pair, peerstore=peerstore)
    remote_transport = InsecureTransport(remote_key_pair, peerstore=None)

    # Run handshake with mismatched peer_id
    # (expecting remote_peer_id but sending mismatch_peer_id to cause a failure)
    async def run_local_handshake(nursery_results):
        with trio.move_on_after(5):
            try:
                # Pass mismatch_peer_id instead of remote_peer_id
                # to cause a handshake failure
                local_conn = await local_transport.secure_outbound(
                    local_stream, mismatch_peer_id
                )
                nursery_results["local"] = local_conn
            except HandshakeFailure:
                nursery_results["local_error"] = True

    async def run_remote_handshake(nursery_results):
        with trio.move_on_after(5):
            try:
                remote_conn = await remote_transport.secure_inbound(remote_stream)
                nursery_results["remote"] = remote_conn
            except HandshakeFailure:
                nursery_results["remote_error"] = True

    nursery_results = {}
    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_local_handshake, nursery_results)
        nursery.start_soon(run_remote_handshake, nursery_results)
        await trio.sleep(0.1)

    # Verify that at least one side encountered an error
    assert "local_error" in nursery_results or "remote_error" in nursery_results, (
        "Expected handshake to fail due to peer ID mismatch"
    )

    # Verify that the peerstore remains unchanged
    current_peer_ids = set(peerstore.peer_ids())
    assert current_peer_ids == initial_peer_ids, (
        "Peerstore should remain unchanged when handshake fails"
    )

    # Verify that neither the remote_peer_id nor mismatch_peer_id was added
    assert remote_peer_id not in peerstore.peer_ids(), (
        "Remote peer ID should not be added on handshake failure"
    )
    assert mismatch_peer_id not in peerstore.peer_ids(), (
        "Mismatch peer ID should not be added on handshake failure"
    )


@pytest.mark.trio
async def test_handshake_adds_pubkey_to_existing_peer():
    """
    Test that when a peer ID already exists in the peerstore but without
    a public key, the handshake correctly adds the public key.

    This tests the case where we might have a peer ID from another source
    (like a routing table) but don't yet have its public key.
    """
    # Create key pairs for both sides
    local_key_pair = create_new_key_pair()
    remote_key_pair = create_new_key_pair()

    # Create peer IDs
    remote_peer_id = ID.from_pubkey(remote_key_pair.public_key)

    # Create peerstore and add the peer ID without a public key
    peerstore = PeerStore()

    # Add the peer ID to the peerstore without its public key
    # (adding an address for the peer, which creates the peer entry)
    # This simulates having discovered a peer through DHT or other means
    # without having its public key yet
    peerstore.peer_data_map[remote_peer_id] = PeerData()

    # Verify initial state - the peer ID should exist but without a public key
    assert remote_peer_id in peerstore.peer_ids()
    with pytest.raises(Exception):
        peerstore.pubkey(remote_peer_id)

    # Create memory streams for communication
    local_send, remote_receive = memory_stream_pair()
    remote_send, local_receive = memory_stream_pair()

    # Create adapters
    local_stream = TrioStreamAdapter(local_send, local_receive, is_initiator=True)
    remote_stream = TrioStreamAdapter(remote_send, remote_receive, is_initiator=False)

    # Create transports
    local_transport = InsecureTransport(local_key_pair, peerstore=peerstore)
    remote_transport = InsecureTransport(remote_key_pair, peerstore=None)

    # Run handshake
    async def run_local_handshake(nursery_results):
        with trio.move_on_after(5):
            local_conn = await local_transport.secure_outbound(
                local_stream, remote_peer_id
            )
            nursery_results["local"] = local_conn

    async def run_remote_handshake(nursery_results):
        with trio.move_on_after(5):
            remote_conn = await remote_transport.secure_inbound(remote_stream)
            nursery_results["remote"] = remote_conn

    nursery_results = {}
    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_local_handshake, nursery_results)
        nursery.start_soon(run_remote_handshake, nursery_results)
        await trio.sleep(0.1)  # Give tasks a chance to finish

    local_conn = nursery_results.get("local")
    remote_conn = nursery_results.get("remote")

    # Verify that the handshake succeeded
    assert local_conn is not None, "Local handshake failed"
    assert remote_conn is not None, "Remote handshake failed"

    # Verify that the peer ID is still in the peerstore
    assert remote_peer_id in peerstore.peer_ids()

    # Verify that the public key was added
    stored_pubkey = peerstore.pubkey(remote_peer_id)
    assert stored_pubkey is not None
    assert stored_pubkey.serialize() == remote_key_pair.public_key.serialize()
