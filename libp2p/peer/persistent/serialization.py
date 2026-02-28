"""
Safe serialization utilities for persistent peerstore.

This module provides safe serialization/deserialization functions using Protocol Buffers
instead of pickle to avoid security vulnerabilities.
"""

from collections.abc import Mapping, Sequence
import logging

from multiaddr import Multiaddr

from libp2p.crypto.keys import KeyPair
from libp2p.custom_types import MetadataValue
from libp2p.peer.envelope import Envelope
from libp2p.peer.pb.crypto_pb2 import (
    KeyType as PBKeyType,
    PrivateKey as PBPrivateKey,
    PublicKey as PBPublicKey,
)
from libp2p.peer.peerstore import PeerRecordState

from .pb import (
    PeerAddresses,
    PeerEnvelope,
    PeerKeys,
    PeerLatency,
    PeerMetadata,
    PeerProtocols,
    PeerRecordState as PBPeerRecordState,
)

logger = logging.getLogger(__name__)


class SerializationError(Exception):
    """Raised when serialization or deserialization fails."""


def serialize_addresses(addresses: Sequence[Multiaddr]) -> bytes:
    """
    Serialize a sequence of multiaddresses to bytes.

    :param addresses: Sequence of Multiaddr objects to serialize
    :return: Serialized bytes
    :raises SerializationError: If serialization fails
    """
    try:
        pb_addresses = PeerAddresses()
        pb_addresses.addresses.extend([addr.to_bytes() for addr in addresses])
        return pb_addresses.SerializeToString()
    except Exception as e:
        raise SerializationError(f"Failed to serialize addresses: {e}") from e


def deserialize_addresses(data: bytes) -> list[Multiaddr]:
    """
    Deserialize addresses from bytes.

    :param data: Serialized address data
    :return: List of Multiaddr objects
    :raises SerializationError: If deserialization fails
    """
    try:
        pb_addresses = PeerAddresses()
        pb_addresses.ParseFromString(data)
        return [Multiaddr(addr_bytes) for addr_bytes in pb_addresses.addresses]
    except Exception as e:
        raise SerializationError(f"Failed to deserialize addresses: {e}") from e


def serialize_protocols(protocols: Sequence[str]) -> bytes:
    """
    Serialize a sequence of protocol strings to bytes.

    :param protocols: Sequence of protocol strings to serialize
    :return: Serialized bytes
    :raises SerializationError: If serialization fails
    """
    try:
        pb_protocols = PeerProtocols()
        pb_protocols.protocols.extend(protocols)
        return pb_protocols.SerializeToString()
    except Exception as e:
        raise SerializationError(f"Failed to serialize protocols: {e}") from e


def deserialize_protocols(data: bytes) -> list[str]:
    """
    Deserialize protocols from bytes.

    :param data: Serialized protocol data
    :return: List of protocol strings
    :raises SerializationError: If deserialization fails
    """
    try:
        pb_protocols = PeerProtocols()
        pb_protocols.ParseFromString(data)
        return list(pb_protocols.protocols)
    except Exception as e:
        raise SerializationError(f"Failed to deserialize protocols: {e}") from e


# Internal serializable value type: includes bytes for key serialization.
_SerializableValue = MetadataValue | bytes


def serialize_metadata(
    metadata: Mapping[str, _SerializableValue],
) -> bytes:
    """
    Serialize metadata dictionary to bytes.

    :param metadata: Dictionary of metadata to serialize
    :return: Serialized bytes
    :raises SerializationError: If serialization fails
    """
    try:
        pb_metadata = PeerMetadata()
        for key, value in metadata.items():
            # Convert value to bytes if it's not already
            if isinstance(value, bytes):
                pb_metadata.metadata[key] = value
            elif isinstance(value, str):
                pb_metadata.metadata[key] = value.encode("utf-8")
            elif isinstance(value, (int, float)):
                pb_metadata.metadata[key] = str(value).encode("utf-8")
            else:
                # For other types, convert to string representation
                pb_metadata.metadata[key] = str(value).encode("utf-8")
        return pb_metadata.SerializeToString()
    except Exception as e:
        raise SerializationError(f"Failed to serialize metadata: {e}") from e


def deserialize_metadata(data: bytes) -> dict[str, bytes]:
    """
    Deserialize metadata from bytes.

    :param data: Serialized metadata data
    :return: Dictionary of metadata (values as bytes)
    :raises SerializationError: If deserialization fails
    """
    try:
        pb_metadata = PeerMetadata()
        pb_metadata.ParseFromString(data)
        return dict(pb_metadata.metadata)
    except Exception as e:
        raise SerializationError(f"Failed to deserialize metadata: {e}") from e


def serialize_keypair(keypair: KeyPair) -> bytes:
    """
    Serialize a keypair to bytes.

    :param keypair: KeyPair to serialize
    :return: Serialized bytes
    :raises SerializationError: If serialization fails
    """
    try:
        pb_keys = PeerKeys()

        # Serialize public key
        if keypair.public_key:
            pb_public_key = PBPublicKey()

            key_type = keypair.public_key.get_type()
            # Map from libp2p KeyType to protobuf KeyType
            if key_type.value == 0:  # RSA
                pb_public_key.Type = PBKeyType.RSA
            elif key_type.value == 1:  # Ed25519
                pb_public_key.Type = PBKeyType.Ed25519
            elif key_type.value == 2:  # Secp256k1
                pb_public_key.Type = PBKeyType.Secp256k1
            elif key_type.value == 3:  # ECDSA
                pb_public_key.Type = PBKeyType.ECDSA
            else:
                raise SerializationError(f"Unsupported key type: {key_type}")
            pb_public_key.Data = keypair.public_key.serialize()
            pb_keys.public_key.CopyFrom(pb_public_key)

        # Serialize private key
        if keypair.private_key:
            pb_private_key = PBPrivateKey()

            key_type = keypair.private_key.get_type()
            # Map from libp2p KeyType to protobuf KeyType
            if key_type.value == 0:  # RSA
                pb_private_key.Type = PBKeyType.RSA
            elif key_type.value == 1:  # Ed25519
                pb_private_key.Type = PBKeyType.Ed25519
            elif key_type.value == 2:  # Secp256k1
                pb_private_key.Type = PBKeyType.Secp256k1
            elif key_type.value == 3:  # ECDSA
                pb_private_key.Type = PBKeyType.ECDSA
            else:
                raise SerializationError(f"Unsupported key type: {key_type}")
            pb_private_key.Data = keypair.private_key.serialize()
            pb_keys.private_key.CopyFrom(pb_private_key)

        return pb_keys.SerializeToString()
    except Exception as e:
        raise SerializationError(f"Failed to serialize keypair: {e}") from e


def deserialize_keypair(data: bytes) -> KeyPair:
    """
    Deserialize a keypair from bytes.

    :param data: Serialized keypair data
    :return: KeyPair object
    :raises SerializationError: If deserialization fails
    """
    try:
        pb_keys = PeerKeys()
        pb_keys.ParseFromString(data)

        from libp2p.crypto.serialization import (
            deserialize_private_key,
            deserialize_public_key,
        )

        public_key = None
        private_key = None

        if pb_keys.HasField("public_key"):
            public_key = deserialize_public_key(pb_keys.public_key.Data)

        if pb_keys.HasField("private_key"):
            private_key = deserialize_private_key(pb_keys.private_key.Data)

        # KeyPair requires both keys to be non-None
        if private_key is not None and public_key is not None:
            return KeyPair(private_key, public_key)
        elif private_key is not None:
            # If we only have private key, derive public key
            return KeyPair(private_key, private_key.get_public_key())
        else:
            # We can't create a KeyPair with only public key
            raise SerializationError("Cannot create KeyPair with only public key")
    except Exception as e:
        raise SerializationError(f"Failed to deserialize keypair: {e}") from e


def serialize_latency(latency_ns: int) -> bytes:
    """
    Serialize latency to bytes.

    :param latency_ns: Latency in nanoseconds
    :return: Serialized bytes
    :raises SerializationError: If serialization fails
    """
    try:
        pb_latency = PeerLatency()
        pb_latency.latency_ns = latency_ns
        return pb_latency.SerializeToString()
    except Exception as e:
        raise SerializationError(f"Failed to serialize latency: {e}") from e


def deserialize_latency(data: bytes) -> int:
    """
    Deserialize latency from bytes.

    :param data: Serialized latency data
    :return: Latency in nanoseconds
    :raises SerializationError: If deserialization fails
    """
    try:
        pb_latency = PeerLatency()
        pb_latency.ParseFromString(data)
        return pb_latency.latency_ns
    except Exception as e:
        raise SerializationError(f"Failed to deserialize latency: {e}") from e


def serialize_envelope(envelope: Envelope) -> bytes:
    """
    Serialize an envelope to bytes.

    :param envelope: Envelope to serialize
    :return: Serialized bytes
    :raises SerializationError: If serialization fails
    """
    try:
        pb_envelope_wrapper = PeerEnvelope()

        # Use the existing envelope's marshal_envelope method if available
        if hasattr(envelope, "marshal_envelope"):
            envelope_bytes = envelope.marshal_envelope()
            from libp2p.peer.pb.envelope_pb2 import Envelope as PBEnvelope

            pb_envelope = PBEnvelope()
            pb_envelope.ParseFromString(envelope_bytes)
            pb_envelope_wrapper.envelope.CopyFrom(pb_envelope)
        else:
            # Fallback: construct envelope manually
            from libp2p.peer.pb.envelope_pb2 import Envelope as PBEnvelope

            pb_envelope = PBEnvelope()
            pb_envelope.payload_type = envelope.payload_type
            pb_envelope.payload = envelope.raw_payload
            pb_envelope.signature = envelope.signature
            if envelope.public_key:
                # Convert the public key to protobuf format
                from libp2p.peer.envelope import pub_key_to_protobuf

                pb_envelope.public_key.CopyFrom(
                    pub_key_to_protobuf(envelope.public_key)
                )
            pb_envelope_wrapper.envelope.CopyFrom(pb_envelope)

        return pb_envelope_wrapper.SerializeToString()
    except Exception as e:
        raise SerializationError(f"Failed to serialize envelope: {e}") from e


def deserialize_envelope(data: bytes) -> Envelope:
    """
    Deserialize an envelope from bytes.

    :param data: Serialized envelope data
    :return: Envelope object
    :raises SerializationError: If deserialization fails
    """
    try:
        pb_envelope_wrapper = PeerEnvelope()
        pb_envelope_wrapper.ParseFromString(data)

        # Construct envelope manually from protobuf data
        pb_envelope = pb_envelope_wrapper.envelope

        # Convert protobuf public key back to crypto public key
        from libp2p.crypto.serialization import deserialize_public_key

        public_key_data = pb_envelope.public_key.SerializeToString()
        public_key = deserialize_public_key(public_key_data)

        return Envelope(
            public_key=public_key,
            payload_type=pb_envelope.payload_type,
            raw_payload=pb_envelope.payload,
            signature=pb_envelope.signature,
        )
    except Exception as e:
        raise SerializationError(f"Failed to deserialize envelope: {e}") from e


def serialize_record_state(state: "PeerRecordState") -> bytes:
    """
    Serialize a peer record state to bytes.

    :param state: PeerRecordState to serialize
    :return: Serialized bytes
    :raises SerializationError: If serialization fails
    """
    try:
        pb_state = PBPeerRecordState()

        # PeerRecordState is a simple class with envelope and seq
        # For now, we'll just mark it as VALID since we don't have state info
        # In the future, this could be extended to track actual state
        pb_state.state = PBPeerRecordState.State.VALID
        return pb_state.SerializeToString()
    except Exception as e:
        raise SerializationError(f"Failed to serialize record state: {e}") from e


def deserialize_record_state(data: bytes) -> "PeerRecordState":
    """
    Deserialize a peer record state from bytes.

    :param data: Serialized record state data
    :return: PeerRecordState
    :raises SerializationError: If deserialization fails
    """
    try:
        pb_state = PBPeerRecordState()
        pb_state.ParseFromString(data)

        # Since we can't reconstruct the full PeerRecordState without the envelope
        # and sequence number (seq), we'll need to return a placeholder. This is a
        # limitation of the current design. In practice, the record state should
        # be stored together with its envelope and seq.
        from libp2p.crypto.ed25519 import Ed25519PublicKey
        from libp2p.peer.envelope import Envelope
        from libp2p.peer.peerstore import PeerRecordState

        # Create a dummy envelope for now
        dummy_key = Ed25519PublicKey.from_bytes(b"\x00" * 32)
        dummy_envelope = Envelope(
            public_key=dummy_key, payload_type=b"", raw_payload=b"", signature=b""
        )

        return PeerRecordState(dummy_envelope, 0)
    except Exception as e:
        raise SerializationError(f"Failed to deserialize record state: {e}") from e
