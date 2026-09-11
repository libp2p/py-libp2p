"""
Utility functions for the circuit v2 module.
"""

import logging
from typing import Any, TypeVar

from libp2p.abc import IHost
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import (
    ID,
)
from libp2p.utils.varint import (
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)

from .pb.circuit_pb2 import HopMessage, StopMessage

logger = logging.getLogger(__name__)

MsgT = TypeVar("MsgT")


async def write_delimited_msg(stream: Any, msg: Any) -> None:
    """
    Write a protobuf message with an unsigned-varint length prefix.

    Circuit relay v2 (HOP/STOP) and DCUtR messages are length-delimited on
    the wire per the libp2p specs; peers written against the spec (e.g.
    rust-libp2p, go-libp2p) reject raw undelimited messages.
    """
    await stream.write(encode_varint_prefixed(msg.SerializeToString()))


async def read_delimited_msg(stream: Any, msg_cls: type[MsgT]) -> MsgT:
    """
    Read one unsigned-varint length-prefixed protobuf message from a stream.
    """
    data = await read_varint_prefixed_bytes(stream)
    msg = msg_cls()
    msg.ParseFromString(data)
    return msg


def maybe_consume_signed_record(
    msg: HopMessage | StopMessage, host: IHost, peer_id: ID | None = None
) -> bool:
    """
    Attempt to parse and store a signed peer record(Envelope) received
    from the HOP or STOP message.If the record is invalid, the peer-id
    does not match, or updating the peerstore fails, the function logs an
    error and returns False.

    Parameters
    ----------
    msg : HopMessage | StopMessage
        The protobuf message received during relay communication. Can be either
        `HopMessage` containing a `signedRecord` field or `StopMessage` with a
        `senderRecord` field.
    host : IHost
        The local host instance, providing access to the peerstore for storing
        verified peer records.
    peer_id : ID | None, optional
        The expected peer ID for record validation. If provided, the peer ID
        inside the record must match this value.

    Returns
    -------
    bool
        True if a valid signed peer record was successfully consumed and stored,
        False otherwise.

    """
    if isinstance(msg, StopMessage):
        if msg.HasField("senderRecord"):
            try:
                # Convert the signed-peer-record(Envelope) from
                # protobuf bytes
                envelope, record = consume_envelope(
                    msg.senderRecord,
                    "libp2p-peer-record",
                )
                if not (isinstance(peer_id, ID) and record.peer_id == peer_id):
                    return False
                # Use the default  TTL of 2 hours (7200 seconds)
                if not host.get_peerstore().consume_peer_record(envelope, 7200):
                    logger.error("Failed to update the Certified-Addr-Book")
                    return False
            except Exception as e:
                logger.error("Failed to update the Certified-Addr-Book: %s", e)
                return False
    elif isinstance(msg, HopMessage):
        if msg.HasField("senderRecord"):
            try:
                # Convert the signed-peer-record(Envelope) from
                # protobuf bytes
                envelope, record = consume_envelope(
                    msg.senderRecord,
                    "libp2p-peer-record",
                )
                if not (isinstance(peer_id, ID) and record.peer_id == peer_id):
                    return False
                # Use the default TTL of 2 hours (7200 seconds)
                if not host.get_peerstore().consume_peer_record(envelope, 7200):
                    logger.error("Failed to update the Certified-Addr-Book")
                    return False
            except Exception as e:
                logger.error(
                    "Failed to update the Certified-Addr-Book: %s",
                    e,
                )
                return False
    return True
