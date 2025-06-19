"""
Peer record implementation for signed peer addressing information.

Based on libp2p RFC 0003: https://github.com/libp2p/specs/blob/master/RFC/0003-routing-records.md
"""

import time
from collections.abc import (
    Sequence,
)
from typing import (
    Any,
)

import multiaddr

from libp2p.crypto.keys import (
    PrivateKey,
)
from libp2p.peer.id import (
    ID,
)

from .envelope import (
    Envelope,
)
from .pb import (
    PeerRecord as PeerRecordPB,
)

# Multicodec for libp2p peer records (0x0301)
LIBP2P_PEER_RECORD_CODEC = b'\x03\x01'


class PeerRecord:
    """
    PeerRecord represents verifiable peer addressing information.
    
    It contains a peer's ID, addresses where it can be reached, and a sequence
    number to enforce freshness. The record can be signed to create a
    verifiable envelope.
    """

    def __init__(
        self,
        peer_id: ID,
        addrs: Sequence[multiaddr.Multiaddr],
        seq: int | None = None,
    ) -> None:
        """
        Initialize a PeerRecord.
        
        Args:
            peer_id: The peer ID
            addrs: List of multiaddresses where the peer can be reached
            seq: Sequence number for freshness (defaults to current timestamp)
        """
        self.peer_id = peer_id
        self.addrs = list(addrs)
        self.seq = seq if seq is not None else int(time.time() * 1000)  # milliseconds

    def serialize(self) -> bytes:
        """
        Serialize the peer record to bytes.
        
        Returns:
            The serialized peer record
        """
        pb = PeerRecordPB(
            peer_id=self.peer_id.to_bytes(),
            addrs=[addr.to_bytes() for addr in self.addrs],
            seq=self.seq,
        )
        return pb.SerializeToString()

    @classmethod
    def deserialize(cls, data: bytes) -> "PeerRecord":
        """
        Deserialize a peer record from bytes.
        
        Args:
            data: The serialized peer record data
            
        Returns:
            The deserialized PeerRecord
            
        Raises:
            ValueError: If the data is invalid or cannot be deserialized
        """
        try:
            pb = PeerRecordPB()
            pb.ParseFromString(data)
            
            peer_id = ID(pb.peer_id)
            addrs = [multiaddr.Multiaddr(addr_bytes) for addr_bytes in pb.addrs]
            
            return cls(
                peer_id=peer_id,
                addrs=addrs,
                seq=pb.seq,
            )
        except Exception as e:
            raise ValueError(f"Failed to deserialize peer record: {e}") from e

    def sign(self, private_key: PrivateKey) -> Envelope:
        """
        Sign the peer record to create a verifiable envelope.
        
        Args:
            private_key: The private key to sign with
            
        Returns:
            A signed envelope containing this peer record
            
        Raises:
            ValueError: If the private key doesn't match the peer ID
        """
        # Verify that the private key matches the peer ID
        expected_peer_id = ID.from_pubkey(private_key.get_public_key())
        if expected_peer_id != self.peer_id:
            raise ValueError(
                f"Private key peer ID {expected_peer_id} does not match "
                f"record peer ID {self.peer_id}"
            )

        # Serialize the record and create envelope with proper payload type
        record_data = self.serialize()
        
        return Envelope.create(
            payload_type=LIBP2P_PEER_RECORD_CODEC,
            payload=record_data, 
            private_key=private_key
        )

    @classmethod
    def from_envelope(cls, envelope: Envelope) -> "PeerRecord":
        """
        Extract a peer record from a signed envelope.
        
        Args:
            envelope: The signed envelope to extract from
            
        Returns:
            The peer record contained in the envelope
            
        Raises:
            ValueError: If the envelope doesn't contain a valid peer record
        """
        # Verify the envelope signature
        if not envelope.verify():
            raise ValueError("Envelope signature verification failed")

        # Verify this is a peer record envelope
        if envelope.payload_type != LIBP2P_PEER_RECORD_CODEC:
            raise ValueError(
                f"Envelope does not contain a peer record: "
                f"expected payload type {LIBP2P_PEER_RECORD_CODEC.hex()}, "
                f"got {envelope.payload_type.hex()}"
            )

        # Deserialize the peer record directly from payload
        peer_record = cls.deserialize(envelope.payload)
        
        # Verify that the peer ID matches the envelope signer
        envelope_peer_id = envelope.peer_id()
        if peer_record.peer_id != envelope_peer_id:
            raise ValueError(
                f"Peer record ID {peer_record.peer_id} does not match "
                f"envelope signer ID {envelope_peer_id}"
            )

        return peer_record

    def is_newer_than(self, other: "PeerRecord") -> bool:
        """
        Check if this record is newer than another record.
        
        Args:
            other: The other peer record to compare against
            
        Returns:
            True if this record has a higher sequence number
        """
        return self.seq > other.seq

    def __eq__(self, other: Any) -> bool:
        """Check equality with another peer record."""
        return (
            isinstance(other, PeerRecord)
            and self.peer_id == other.peer_id
            and self.addrs == other.addrs
            and self.seq == other.seq
        )

    def __repr__(self) -> str:
        """String representation of the peer record."""
        return (
            f"PeerRecord(peer_id={self.peer_id}, "
            f"addrs={len(self.addrs)} addresses, "
            f"seq={self.seq})"
        ) 