import pytest
import trio
from trio.testing import memory_stream_pair

from libp2p.abc import IRawConnection
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
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
