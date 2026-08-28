"""
messages.py
-----------

Wire-format definitions for the ``/ml/checkpoint/1.0.0`` libp2p protocol.

Every message is a small JSON object with a ``type`` discriminator field.
These messages are the *only* thing that crosses the network directly over
libp2p -- the checkpoint bytes themselves always travel through IPFS (see
README > Direct vs IPFS Communication).

Three logical exchanges, five message types:

* ``sync_request`` / ``sync_response``
    "What's the latest checkpoint you know about?" Used by a peer that just
    (re)joined the network, including one that was offline for a while.

* ``checkpoint_announcement``
    Fire-and-forget-style push: "I just made a new checkpoint." Sent right
    after a training round completes, to whichever peer is currently
    connected.

* ``checkpoint_request`` / ``checkpoint_available``
    "Give me checkpoint <id> specifically" / the answer to that, in case a
    peer wants an explicit round rather than just the latest.
"""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass
from typing import Any, ClassVar

MSG_SYNC_REQUEST = "sync_request"
MSG_SYNC_RESPONSE = "sync_response"
MSG_CHECKPOINT_ANNOUNCEMENT = "checkpoint_announcement"
MSG_CHECKPOINT_REQUEST = "checkpoint_request"
MSG_CHECKPOINT_AVAILABLE = "checkpoint_available"

_ALL_TYPES = {
    MSG_SYNC_REQUEST,
    MSG_SYNC_RESPONSE,
    MSG_CHECKPOINT_ANNOUNCEMENT,
    MSG_CHECKPOINT_REQUEST,
    MSG_CHECKPOINT_AVAILABLE,
}


class InvalidMessageError(ValueError):
    """Raised when a payload doesn't match any known message schema."""


@dataclass
class SyncRequest:
    """"What checkpoint round am I missing?" -- sent with the requester's
    current local round so the responder can decide what (if anything) to
    offer back."""

    type: ClassVar[str] = MSG_SYNC_REQUEST
    latest_round: int

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "latest_round": self.latest_round}


@dataclass
class SyncResponse:
    """Reply to a SyncRequest. ``cid`` and ``round`` describe the
    responder's own latest checkpoint; ``has_checkpoint`` is False if the
    responder has never produced one yet."""

    type: ClassVar[str] = MSG_SYNC_RESPONSE
    has_checkpoint: bool
    latest_round: int = 0
    cid: str | None = None
    model_hash: str | None = None
    peer_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "has_checkpoint": self.has_checkpoint,
            "latest_round": self.latest_round,
            "cid": self.cid,
            "model_hash": self.model_hash,
            "peer_id": self.peer_id,
        }


@dataclass
class CheckpointAnnouncement:
    """Unsolicited push sent right after a new checkpoint is created."""

    type: ClassVar[str] = MSG_CHECKPOINT_ANNOUNCEMENT
    checkpoint_id: str
    round: int
    cid: str
    sender: str
    model_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "checkpoint_id": self.checkpoint_id,
            "round": self.round,
            "cid": self.cid,
            "sender": self.sender,
            "model_hash": self.model_hash,
        }


@dataclass
class CheckpointRequest:
    """Ask a peer for one specific checkpoint by id."""

    type: ClassVar[str] = MSG_CHECKPOINT_REQUEST
    checkpoint_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "checkpoint_id": self.checkpoint_id}


@dataclass
class CheckpointAvailable:
    """Answer to a CheckpointRequest (or ack of an announcement)."""

    type: ClassVar[str] = MSG_CHECKPOINT_AVAILABLE
    checkpoint_id: str
    found: bool
    cid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "checkpoint_id": self.checkpoint_id,
            "found": self.found,
            "cid": self.cid,
        }


_TYPE_TO_CLASS = {
    MSG_SYNC_REQUEST: SyncRequest,
    MSG_SYNC_RESPONSE: SyncResponse,
    MSG_CHECKPOINT_ANNOUNCEMENT: CheckpointAnnouncement,
    MSG_CHECKPOINT_REQUEST: CheckpointRequest,
    MSG_CHECKPOINT_AVAILABLE: CheckpointAvailable,
}


def parse_message(data: dict[str, Any]) -> Any:
    """Validate and deserialize a raw dict (as received over the wire) into
    the matching message dataclass.

    Raises :class:`InvalidMessageError` for anything that doesn't have a
    recognized ``type``, or is missing required fields -- callers should
    treat that as "reject the message", not crash the peer.
    """
    if not isinstance(data, dict):
        raise InvalidMessageError(f"Message must be a JSON object, got {type(data)}")

    msg_type = data.get("type")
    if msg_type not in _ALL_TYPES:
        raise InvalidMessageError(f"Unknown or missing message type: {msg_type!r}")

    cls = _TYPE_TO_CLASS[msg_type]
    payload = {k: v for k, v in data.items() if k != "type"}
    field_names = {f for f in cls.__dataclass_fields__}
    unknown = set(payload) - field_names
    if unknown:
        raise InvalidMessageError(f"Unexpected fields for {msg_type}: {unknown}")

    required = {
        name
        for name, f in cls.__dataclass_fields__.items()
        if f.default is MISSING and f.default_factory is MISSING
    }
    missing = required - set(payload)
    if missing:
        raise InvalidMessageError(f"Missing required fields for {msg_type}: {missing}")

    try:
        return cls(**payload)
    except TypeError as exc:
        raise InvalidMessageError(f"Malformed {msg_type} payload: {exc}") from exc


def dump_message(message: Any) -> dict[str, Any]:
    """Serialize any of the message dataclasses back into a plain dict."""
    if hasattr(message, "to_dict"):
        return message.to_dict()
    return asdict(message)
