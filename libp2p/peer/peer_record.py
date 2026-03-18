from collections.abc import Sequence
import threading
import time
from typing import Any

from multiaddr import Multiaddr
from multicodec import Code, get_prefix
from multicodec.code_table import LIBP2P_PEER_RECORD

from libp2p.abc import IPeerRecord
from libp2p.peer.id import ID
import libp2p.peer.pb.peer_record_pb2 as pb
from libp2p.peer.peerinfo import PeerInfo

PEER_RECORD_ENVELOPE_DOMAIN = "libp2p-peer-record"
PEER_RECORD_ENVELOPE_CODE: Code = LIBP2P_PEER_RECORD
PEER_RECORD_ENVELOPE_PAYLOAD_TYPE = get_prefix(str(PEER_RECORD_ENVELOPE_CODE))

_last_timestamp_lock = threading.Lock()
_last_timestamp: int = 0


class PeerRecord(IPeerRecord):
    """
    A record that contains metatdata about a peer in the libp2p network.

    This includes:
    - `peer_id`: The peer's globally unique indentifier.
    - `addrs`: A list of the peer's publicly reachable multiaddrs.
    - `seq`: A strictly monotonically increasing timestamp used
    to order records over time.

    PeerRecords are designed to be signed and transmitted in libp2p routing Envelopes.
    """

    peer_id: ID
    addrs: list[Multiaddr]
    seq: int

    def __init__(
        self,
        peer_id: ID | None = None,
        addrs: list[Multiaddr] | None = None,
        seq: int | None = None,
    ) -> None:
        """
        Initialize a new PeerRecord.
        If `seq` is not provided, a timestamp-based strictly increasing sequence
        number will be generated.

        :param peer_id: ID of the peer this record refers to.
        :param addrs: Public multiaddrs of the peer.
        :param seq: Monotonic sequence number.

        """
        if peer_id is not None:
            self.peer_id = peer_id
        self.addrs = addrs or []
        if seq is not None:
            self.seq = seq
        else:
            self.seq = timestamp_seq()

    def __repr__(self) -> str:
        return (
            f"PeerRecord(\n"
            f"  peer_id={self.peer_id},\n"
            f"  multiaddrs={[str(m) for m in self.addrs]},\n"
            f"  seq={self.seq}\n"
            f")"
        )

    def domain(self) -> str:
        """
        Return the domain string associated with this PeerRecord.

        Used during record signing and envelope validation to identify the record type.
        """
        return PEER_RECORD_ENVELOPE_DOMAIN

    def codec(self) -> bytes:
        """
        Return the codec identifier for PeerRecords.

        This binary perfix helps distinguish PeerRecords in serialized envelopes.
        """
        return PEER_RECORD_ENVELOPE_PAYLOAD_TYPE

    def to_protobuf(self) -> pb.PeerRecord:
        """
        Convert the current PeerRecord into a ProtoBuf PeerRecord message.

        :raises ValueError: if peer_id serialization fails.
        :return: A ProtoBuf-encoded PeerRecord message object.
        """
        try:
            id_bytes = self.peer_id.to_bytes()
        except Exception as e:
            raise ValueError(f"failed to marshal peer_id: {e}")

        msg = pb.PeerRecord()
        msg.peer_id = id_bytes
        msg.seq = self.seq
        msg.addresses.extend(addrs_to_protobuf(self.addrs))
        return msg

    def marshal_record(self) -> bytes:
        """
        Serialize a PeerRecord into raw bytes suitable for embedding in an Envelope.

        This is typically called during the process of signing or sealing the record.
        :raises ValueError: if serialization to protobuf fails.
        :return: Serialized PeerRecord bytes.
        """
        try:
            msg = self.to_protobuf()
            return msg.SerializeToString()
        except Exception as e:
            raise ValueError(f"failed to marshal PeerRecord: {e}")

    def equal(self, other: Any) -> bool:
        """
        Check if this PeerRecord is identical to another.

        Two PeerRecords are considered equal if:
        - Their peer IDs match.
        - Their sequence numbers are identical.
        - Their address lists are identical and in the same order.

        :param other: Another PeerRecord instance.
        :return: True if all fields mathch, False otherwise.
        """
        if isinstance(other, PeerRecord):
            if self.peer_id == other.peer_id:
                if self.seq == other.seq:
                    if len(self.addrs) == len(other.addrs):
                        for a1, a2 in zip(self.addrs, other.addrs):
                            if a1 == a2:
                                continue
                            else:
                                return False
                        return True
        return False


def unmarshal_record(data: bytes) -> PeerRecord:
    """
    Deserialize a PeerRecord from its serialized byte representation.

    Typically used when receiveing a PeerRecord inside a signed routing Envelope.

    :param data: Serialized protobuf-encoded bytes.
    :raises ValueError: if parsing or conversion fails.
    :reurn: A valid PeerRecord instance.
    """
    if data is None:
        raise ValueError("cannot unmarshal PeerRecord from None")

    msg = pb.PeerRecord()
    try:
        msg.ParseFromString(data)
    except Exception as e:
        raise ValueError(f"Failed to parse PeerRecord protobuf: {e}")

    try:
        record = peer_record_from_protobuf(msg)
    except Exception as e:
        raise ValueError(f"Failed to convert protobuf to PeerRecord: {e}")

    return record


def timestamp_seq() -> int:
    """
    Generate a strictly increasing timestamp-based sequence number.

    Ensures that even if multiple PeerRecords are generated in the same nanosecond,
    their `seq` values will still be strictly increasing by using a lock to track the
    last value.

    :return: A strictly increasing integer timestamp.
    """
    global _last_timestamp
    now = int(time.time_ns())
    with _last_timestamp_lock:
        if now <= _last_timestamp:
            now = _last_timestamp + 1
        _last_timestamp = now
    return now


def peer_record_from_peer_info(info: PeerInfo) -> PeerRecord:
    """
    Create a PeerRecord from a PeerInfo object.

    This automatically assigns a timestamp-based sequence number to the record.
    :param info: A PeerInfo instance (contains peer_id and addrs).
    :return: A PeerRecord instance.
    """
    record = PeerRecord()
    record.peer_id = info.peer_id
    record.addrs = info.addrs
    return record


def peer_record_from_protobuf(msg: pb.PeerRecord) -> PeerRecord:
    """
    Convert a protobuf PeerRecord message into a PeerRecord object.

    :param msg: Protobuf PeerRecord message.
    :raises ValueError: if the peer_id cannot be parsed.
    :return: A deserialized PeerRecord instance.
    """
    try:
        peer_id = ID(msg.peer_id)
    except Exception as e:
        raise ValueError(f"Failed to unmarshal peer_id: {e}")

    addrs = addrs_from_protobuf(msg.addresses)
    seq = msg.seq

    return PeerRecord(peer_id, addrs, seq)


def addrs_from_protobuf(addrs: Sequence[pb.PeerRecord.AddressInfo]) -> list[Multiaddr]:
    """
    Convert a list of protobuf address records to Multiaddr objects.

    :param addrs: A list of protobuf PeerRecord.AddressInfo messages.
    :return: A list of decoded Multiaddr instances (invalid ones are skipped).
    """
    out = []
    for addr_info in addrs:
        try:
            addr = Multiaddr(addr_info.multiaddr)
            out.append(addr)
        except Exception:
            continue
    return out


def addrs_to_protobuf(addrs: list[Multiaddr]) -> list[pb.PeerRecord.AddressInfo]:
    """
    Convert a list of Multiaddr objects into their protobuf representation.

    :param addrs: A list of Multiaddr instances.
    :return: A list of PeerRecord.AddressInfo protobuf messages.
    """
    out = []
    for addr in addrs:
        addr_info = pb.PeerRecord.AddressInfo()
        addr_info.multiaddr = addr.to_bytes()
        out.append(addr_info)
    return out
