"""
Tests for p2p_checkpoint.messages (serialization/deserialization/validation)
and, using two in-process libp2p hosts, the /ml/checkpoint/1.0.0 protocol
handlers in p2p_checkpoint.protocol / peer.py.
"""

from __future__ import annotations

import pytest
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import PeerInfo
from libp2p import new_host
from libp2p.utils.address_validation import get_available_interfaces

from p2p_checkpoint.messages import (
    CheckpointAnnouncement,
    CheckpointAvailable,
    CheckpointRequest,
    InvalidMessageError,
    SyncRequest,
    SyncResponse,
    dump_message,
    parse_message,
)
from p2p_checkpoint.protocol import CheckpointProtocol


# ------------------------------------------------------------------------ #
# Message (de)serialization
# ------------------------------------------------------------------------ #
def test_sync_request_round_trip():
    msg = SyncRequest(latest_round=7)
    data = dump_message(msg)
    assert data == {"type": "sync_request", "latest_round": 7}
    parsed = parse_message(data)
    assert parsed == msg


def test_sync_response_round_trip_with_checkpoint():
    msg = SyncResponse(
        has_checkpoint=True, latest_round=3, cid="bafy123", model_hash="sha256:abc",
        peer_id="12D3xyz",
    )
    parsed = parse_message(dump_message(msg))
    assert parsed == msg


def test_sync_response_round_trip_without_checkpoint():
    msg = SyncResponse(has_checkpoint=False)
    parsed = parse_message(dump_message(msg))
    assert parsed.has_checkpoint is False
    assert parsed.latest_round == 0


def test_checkpoint_announcement_round_trip():
    msg = CheckpointAnnouncement(
        checkpoint_id="checkpoint-002", round=2, cid="bafy456", sender="12D3abc"
    )
    parsed = parse_message(dump_message(msg))
    assert parsed == msg


def test_checkpoint_request_and_available_round_trip():
    req = CheckpointRequest(checkpoint_id="checkpoint-001")
    assert parse_message(dump_message(req)) == req

    resp = CheckpointAvailable(checkpoint_id="checkpoint-001", found=True, cid="bafy789")
    assert parse_message(dump_message(resp)) == resp


def test_invalid_message_missing_type():
    with pytest.raises(InvalidMessageError):
        parse_message({"latest_round": 1})


def test_invalid_message_unknown_type():
    with pytest.raises(InvalidMessageError):
        parse_message({"type": "carrier_pigeon"})


def test_invalid_message_missing_required_field():
    with pytest.raises(InvalidMessageError):
        parse_message({"type": "checkpoint_request"})  # missing checkpoint_id


def test_invalid_message_unexpected_field():
    with pytest.raises(InvalidMessageError):
        parse_message({"type": "sync_request", "latest_round": 1, "extra": "nope"})


def test_invalid_message_not_a_dict():
    with pytest.raises(InvalidMessageError):
        parse_message(["not", "a", "dict"])  # type: ignore[arg-type]


# ------------------------------------------------------------------------ #
# Protocol wiring over real (in-process) libp2p hosts
# ------------------------------------------------------------------------ #
class _StubProvider:
    """Minimal CheckpointProvider for testing the protocol layer in
    isolation from Peer/IPFS/the model."""

    def __init__(self):
        self.received_sync_requests = []
        self.received_checkpoint_requests = []
        self.received_announcements = []

    def handle_sync_request(self, msg: SyncRequest, sender_peer_id: str) -> SyncResponse:
        self.received_sync_requests.append((msg, sender_peer_id))
        return SyncResponse(has_checkpoint=True, latest_round=5, cid="bafyStub", peer_id="me")

    def handle_checkpoint_request(
        self, msg: CheckpointRequest, sender_peer_id: str
    ) -> CheckpointAvailable:
        self.received_checkpoint_requests.append((msg, sender_peer_id))
        return CheckpointAvailable(checkpoint_id=msg.checkpoint_id, found=True, cid="bafyStub")

    def handle_announcement(
        self, msg: CheckpointAnnouncement, sender_peer_id: str
    ) -> CheckpointAvailable:
        self.received_announcements.append((msg, sender_peer_id))
        return CheckpointAvailable(checkpoint_id=msg.checkpoint_id, found=True, cid=msg.cid)


async def test_sync_request_reaches_handler_and_response_round_trips():
    provider = _StubProvider()

    host_a = new_host(key_pair=create_new_key_pair(b"proto-a" + b"\x00" * 25))
    host_b = new_host(key_pair=create_new_key_pair(b"proto-b" + b"\x00" * 25))

    async with (
        host_a.run(listen_addrs=get_available_interfaces(0)),
        host_b.run(listen_addrs=get_available_interfaces(0)),
    ):
        proto_a = CheckpointProtocol(host_a)
        proto_a.bind(provider)
        proto_b = CheckpointProtocol(host_b)

        info_a = PeerInfo(host_a.get_id(), host_a.get_addrs())
        await host_b.connect(info_a)

        response = await proto_b.send_sync_request(host_a.get_id(), latest_round=1)

        assert isinstance(response, SyncResponse)
        assert response.latest_round == 5
        assert response.cid == "bafyStub"
        assert len(provider.received_sync_requests) == 1
        received_msg, sender = provider.received_sync_requests[0]
        assert received_msg.latest_round == 1
        assert sender == host_b.get_id().to_string()


async def test_checkpoint_request_reaches_handler():
    provider = _StubProvider()

    host_a = new_host(key_pair=create_new_key_pair(b"proto-c" + b"\x00" * 25))
    host_b = new_host(key_pair=create_new_key_pair(b"proto-d" + b"\x00" * 25))

    async with (
        host_a.run(listen_addrs=get_available_interfaces(0)),
        host_b.run(listen_addrs=get_available_interfaces(0)),
    ):
        proto_a = CheckpointProtocol(host_a)
        proto_a.bind(provider)
        proto_b = CheckpointProtocol(host_b)

        info_a = PeerInfo(host_a.get_id(), host_a.get_addrs())
        await host_b.connect(info_a)

        response = await proto_b.send_checkpoint_request(
            host_a.get_id(), checkpoint_id="checkpoint-007"
        )
        assert response.found is True
        assert response.checkpoint_id == "checkpoint-007"
        assert provider.received_checkpoint_requests[0][0].checkpoint_id == "checkpoint-007"


async def test_malformed_request_returns_error_not_crash():
    """A handler wired via CheckpointProtocol.bind must survive/reject a
    request that isn't valid JSON-schema for any known message type,
    without taking the host down."""
    provider = _StubProvider()

    host_a = new_host(key_pair=create_new_key_pair(b"proto-e" + b"\x00" * 25))
    host_b = new_host(key_pair=create_new_key_pair(b"proto-f" + b"\x00" * 25))

    async with (
        host_a.run(listen_addrs=get_available_interfaces(0)),
        host_b.run(listen_addrs=get_available_interfaces(0)),
    ):
        proto_a = CheckpointProtocol(host_a)
        proto_a.bind(provider)

        from libp2p.request_response import JSONCodec, RequestResponse
        from p2p_checkpoint.protocol import PROTOCOL_ID

        info_a = PeerInfo(host_a.get_id(), host_a.get_addrs())
        await host_b.connect(info_a)

        rr_b = RequestResponse(host_b)
        raw = await rr_b.send_request(
            peer_id=host_a.get_id(),
            protocol_ids=[PROTOCOL_ID],
            request={"type": "not_a_real_type"},
            codec=JSONCodec(),
        )
        assert raw["type"] == "error"

        # The host must still be healthy: a legitimate follow-up request works.
        proto_b = CheckpointProtocol(host_b)
        response = await proto_b.send_sync_request(host_a.get_id(), latest_round=0)
        assert isinstance(response, SyncResponse)
