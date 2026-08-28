"""
protocol.py
-----------

Wires the message schemas in ``messages.py`` onto an actual libp2p wire
protocol: ``/ml/checkpoint/1.0.0``.

This sits on top of py-libp2p's ``request_response.RequestResponse`` helper
(one JSON request -> one JSON response over a dedicated stream), rather than
hand-rolling stream reads/writes. That helper already handles opening the
stream, negotiating the protocol id, and framing -- this module just needs
to supply a dict-in/dict-out handler and a typed, validated view of the
messages on both sides.

``CheckpointProvider`` is the seam between networking and application logic:
``protocol.py`` knows nothing about IPFS, SQLite, or scikit-learn, and
``peer.py`` implements the provider without needing to know how libp2p
streams work.
"""

from __future__ import annotations

import logging
from typing import Protocol as TypingProtocol

from libp2p.custom_types import TProtocol
from libp2p.request_response import JSONCodec, RequestResponse

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

logger = logging.getLogger("p2p_checkpoint.protocol")

PROTOCOL_ID = TProtocol("/ml/checkpoint/1.0.0")


class CheckpointProvider(TypingProtocol):
    """The application-level operations the network handler needs.
    Implemented by :class:`p2p_checkpoint.peer.Peer`."""

    def handle_sync_request(self, msg: SyncRequest, sender_peer_id: str) -> SyncResponse: ...

    def handle_checkpoint_request(
        self, msg: CheckpointRequest, sender_peer_id: str
    ) -> CheckpointAvailable: ...

    def handle_announcement(
        self, msg: CheckpointAnnouncement, sender_peer_id: str
    ) -> CheckpointAvailable: ...


class CheckpointProtocol:
    """Owns the libp2p side of the ``/ml/checkpoint/1.0.0`` protocol for a
    single host: registering the inbound handler and issuing outbound
    requests."""

    def __init__(self, host) -> None:
        self.host = host
        self._rr = RequestResponse(host)
        self._codec = JSONCodec()

    # ------------------------------------------------------------------ #
    # Inbound (listener side)
    # ------------------------------------------------------------------ #
    def bind(self, provider: CheckpointProvider) -> None:
        """Register the handler that answers incoming requests on this
        protocol, dispatching by message type to ``provider``."""

        async def handler(request: dict, context) -> dict:
            peer_id = str(context.peer_id)
            try:
                msg = parse_message(request)
            except InvalidMessageError as exc:
                logger.warning("Rejected malformed message from %s: %s", peer_id, exc)
                return {"type": "error", "error": str(exc)}

            try:
                if isinstance(msg, SyncRequest):
                    reply = provider.handle_sync_request(msg, peer_id)
                elif isinstance(msg, CheckpointRequest):
                    reply = provider.handle_checkpoint_request(msg, peer_id)
                elif isinstance(msg, CheckpointAnnouncement):
                    reply = provider.handle_announcement(msg, peer_id)
                else:  # pragma: no cover - parse_message only returns known types
                    return {"type": "error", "error": f"unhandled type {msg}"}
            except Exception as exc:  # noqa: BLE001 - never let a bad peer kill the host
                logger.exception("Error handling %s from %s", msg, peer_id)
                return {"type": "error", "error": str(exc)}

            return dump_message(reply)

        self._rr.set_handler(PROTOCOL_ID, handler=handler, codec=self._codec)

    # ------------------------------------------------------------------ #
    # Outbound (dialer side)
    # ------------------------------------------------------------------ #
    async def send_sync_request(self, peer_id, latest_round: int) -> SyncResponse:
        raw = await self._rr.send_request(
            peer_id=peer_id,
            protocol_ids=[PROTOCOL_ID],
            request=dump_message(SyncRequest(latest_round=latest_round)),
            codec=self._codec,
        )
        return _expect(raw, SyncResponse)

    async def send_checkpoint_request(self, peer_id, checkpoint_id: str) -> CheckpointAvailable:
        raw = await self._rr.send_request(
            peer_id=peer_id,
            protocol_ids=[PROTOCOL_ID],
            request=dump_message(CheckpointRequest(checkpoint_id=checkpoint_id)),
            codec=self._codec,
        )
        return _expect(raw, CheckpointAvailable)

    async def send_announcement(
        self, peer_id, announcement: CheckpointAnnouncement
    ) -> CheckpointAvailable:
        raw = await self._rr.send_request(
            peer_id=peer_id,
            protocol_ids=[PROTOCOL_ID],
            request=dump_message(announcement),
            codec=self._codec,
        )
        return _expect(raw, CheckpointAvailable)


def _expect(raw: dict, expected_type: type):
    if raw.get("type") == "error":
        raise RuntimeError(f"Peer returned an error: {raw.get('error')}")
    msg = parse_message(raw)
    if not isinstance(msg, expected_type):
        raise RuntimeError(f"Expected {expected_type.__name__}, got {type(msg).__name__}")
    return msg
