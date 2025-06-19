"""
Envelope implementation for signed records.

Based on libp2p RFC 0002: https://github.com/libp2p/specs/blob/master/RFC/0002-signed-envelopes.md
"""

from typing import (
    Any,
)

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.crypto.serialization import (
    deserialize_public_key,
)
from libp2p.peer.id import (
    ID,
)

from .pb import (
    Envelope as EnvelopePB,
)

# Domain separation string for libp2p records
LIBP2P_RECORD_DOMAIN = "libp2p-envelope-signature:"


class Envelope:
    """
    Envelope represents a signed record.
    
    It provides authentication and integrity for record data by wrapping it
    with a cryptographic signature and the public key used for signing.
    """

    def __init__(
        self,
        public_key: PublicKey,
        payload_type: bytes,
        payload: bytes,
        signature: bytes,
    ) -> None:
        """
        Initialize an Envelope.
        
        Args:
            public_key: The public key that was used to sign the payload
            payload_type: The type identifier for the payload
            payload: The payload that was signed
            signature: The signature of the payload using the public key
        """
        self.public_key = public_key
        self.payload_type = payload_type
        self.payload = payload
        self.signature = signature

    @classmethod
    def create(
        cls,
        payload_type: bytes,
        payload: bytes,
        private_key: PrivateKey,
    ) -> "Envelope":
        """
        Create and sign a new envelope.
        
        Args:
            payload_type: The type identifier for the payload
            payload: The data to be signed
            private_key: The private key to sign with
            
        Returns:
            A new signed Envelope
        """
        public_key = private_key.get_public_key()
        signature_data = LIBP2P_RECORD_DOMAIN.encode() + payload
        signature = private_key.sign(signature_data)
        
        return cls(
            public_key=public_key,
            payload_type=payload_type,
            payload=payload,
            signature=signature,
        )

    def verify(self) -> bool:
        """
        Verify the envelope signature.
        
        Returns:
            True if the signature is valid, False otherwise
        """
        try:
            signature_data = LIBP2P_RECORD_DOMAIN.encode() + self.payload
            return self.public_key.verify(signature_data, self.signature)
        except Exception:
            return False

    def peer_id(self) -> ID:
        """
        Get the peer ID of the signer.
        
        Returns:
            The peer ID derived from the public key
        """
        return ID.from_pubkey(self.public_key)

    def serialize(self) -> bytes:
        """
        Serialize the envelope to bytes.
        
        Returns:
            The serialized envelope
        """
        pb = EnvelopePB(
            public_key=self.public_key.serialize(),
            payload_type=self.payload_type,
            payload=self.payload,
            signature=self.signature,
        )
        return pb.SerializeToString()

    @classmethod
    def deserialize(cls, data: bytes) -> "Envelope":
        """
        Deserialize an envelope from bytes.
        
        Args:
            data: The serialized envelope data
            
        Returns:
            The deserialized Envelope
            
        Raises:
            ValueError: If the data is invalid or cannot be deserialized
        """
        try:
            pb = EnvelopePB()
            pb.ParseFromString(data)
            
            public_key = deserialize_public_key(pb.public_key)
            
            return cls(
                public_key=public_key,
                payload_type=pb.payload_type,
                payload=pb.payload,
                signature=pb.signature,
            )
        except Exception as e:
            raise ValueError(f"Failed to deserialize envelope: {e}") from e

    def __eq__(self, other: Any) -> bool:
        """Check equality with another envelope."""
        return (
            isinstance(other, Envelope)
            and self.public_key.serialize() == other.public_key.serialize()
            and self.payload_type == other.payload_type
            and self.payload == other.payload
            and self.signature == other.signature
        )

    def __repr__(self) -> str:
        """String representation of the envelope."""
        return (
            f"Envelope(peer_id={self.peer_id()}, "
            f"payload_type={self.payload_type.hex()}, "
            f"payload_len={len(self.payload)}, "
            f"signature_len={len(self.signature)})"
        ) 