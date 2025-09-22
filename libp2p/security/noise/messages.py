from dataclasses import (
    dataclass,
    field,
)
import logging

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.crypto.serialization import (
    deserialize_public_key,
)

from .pb import noise_pb2 as noise_pb

logger = logging.getLogger(__name__)

SIGNED_DATA_PREFIX = "noise-libp2p-static-key:"


@dataclass
class NoiseExtensions:
    """
    Noise protocol extensions for advanced features like WebTransport and early data.

    This class provides support for:
    - WebTransport certificate hashes for WebTransport support
    - Early data payload for 0-RTT support
    """

    webtransport_certhashes: list[bytes] = field(default_factory=list)
    early_data: bytes | None = None

    def to_protobuf(self) -> noise_pb.NoiseExtensions:
        """
        Convert to protobuf message.

        Returns:
            noise_pb.NoiseExtensions: The protobuf message representation

        """
        ext = noise_pb.NoiseExtensions()
        ext.webtransport_certhashes.extend(self.webtransport_certhashes)
        if self.early_data is not None:
            ext.early_data = self.early_data
        return ext

    @classmethod
    def from_protobuf(cls, pb_ext: noise_pb.NoiseExtensions) -> "NoiseExtensions":
        """
        Create from protobuf message.

        Args:
            pb_ext: The protobuf message to convert

        Returns:
            NoiseExtensions: The Python dataclass representation

        """
        early_data = None
        if pb_ext.early_data != b"":
            early_data = pb_ext.early_data
        return cls(
            webtransport_certhashes=list(pb_ext.webtransport_certhashes),
            early_data=early_data,
        )

    def is_empty(self) -> bool:
        """
        Check if extensions are empty (no data).

        Returns:
            bool: True if no extensions data is present

        """
        return not self.webtransport_certhashes and self.early_data is None

    def has_webtransport_certhashes(self) -> bool:
        """
        Check if WebTransport certificate hashes are present.

        Returns:
            bool: True if WebTransport certificate hashes are present

        """
        return bool(self.webtransport_certhashes)

    def has_early_data(self) -> bool:
        """
        Check if early data is present.

        Returns:
            bool: True if early data is present

        """
        return self.early_data is not None


@dataclass
class NoiseHandshakePayload:
    """
    Noise handshake payload containing peer identity and optional extensions.

    This class represents the payload sent during Noise handshake and provides:
    - Peer identity verification through public key and signature
    - Optional early data for 0-RTT support
    - Optional extensions for advanced features like WebTransport
    """

    id_pubkey: PublicKey
    id_sig: bytes
    early_data: bytes | None = None
    extensions: NoiseExtensions | None = None

    def serialize(self) -> bytes:
        """
        Serialize the handshake payload to protobuf bytes.

        Returns:
            bytes: The serialized protobuf message

        Raises:
            ValueError: If the payload is invalid

        """
        if not self.id_pubkey or not self.id_sig:
            raise ValueError("Invalid handshake payload: missing required fields")

        msg = noise_pb.NoiseHandshakePayload(
            identity_key=self.id_pubkey.serialize(), identity_sig=self.id_sig
        )

        # Handle early data: prefer extensions over legacy data field
        if self.extensions is not None and self.extensions.early_data is not None:
            # Early data is in extensions
            msg.extensions.CopyFrom(self.extensions.to_protobuf())
        elif self.early_data is not None:
            # Legacy early data in data field (for backward compatibility)
            msg.data = self.early_data
            if self.extensions is not None:
                # Still include extensions even if early data is in legacy field
                msg.extensions.CopyFrom(self.extensions.to_protobuf())
        elif self.extensions is not None:
            # Extensions without early data
            msg.extensions.CopyFrom(self.extensions.to_protobuf())

        return msg.SerializeToString()

    @classmethod
    def deserialize(cls, protobuf_bytes: bytes) -> "NoiseHandshakePayload":
        """
        Deserialize protobuf bytes to handshake payload.

        Args:
            protobuf_bytes: The serialized protobuf message

        Returns:
            NoiseHandshakePayload: The deserialized handshake payload

        Raises:
            ValueError: If the protobuf data is invalid

        """
        if not protobuf_bytes:
            raise ValueError("Empty protobuf data")

        try:
            msg = noise_pb.NoiseHandshakePayload.FromString(protobuf_bytes)
        except Exception as e:
            raise ValueError(f"Failed to deserialize protobuf: {e}")

        if not msg.identity_key or not msg.identity_sig:
            raise ValueError("Invalid handshake payload: missing required fields")

        extensions = None
        early_data = None

        if msg.HasField("extensions"):
            extensions = NoiseExtensions.from_protobuf(msg.extensions)
            # Early data from extensions takes precedence
            if extensions.early_data is not None:
                early_data = extensions.early_data

        # Fall back to legacy data field if no early data in extensions
        if early_data is None:
            early_data = msg.data if msg.data != b"" else None

        try:
            id_pubkey = deserialize_public_key(msg.identity_key)
        except Exception as e:
            raise ValueError(f"Failed to deserialize public key: {e}")

        return cls(
            id_pubkey=id_pubkey,
            id_sig=msg.identity_sig,
            early_data=early_data,
            extensions=extensions,
        )

    def has_extensions(self) -> bool:
        """
        Check if extensions are present.

        Returns:
            bool: True if extensions are present

        """
        return self.extensions is not None and not self.extensions.is_empty()

    def has_early_data(self) -> bool:
        """
        Check if early data is present (either in extensions or legacy field).

        Returns:
            bool: True if early data is present

        """
        if self.extensions is not None and self.extensions.has_early_data():
            return True
        return self.early_data is not None

    def get_early_data(self) -> bytes | None:
        """
        Get early data, preferring extensions over legacy field.

        Returns:
            bytes | None: The early data if present

        """
        if self.extensions is not None and self.extensions.has_early_data():
            return self.extensions.early_data
        return self.early_data


def make_data_to_be_signed(noise_static_pubkey: PublicKey) -> bytes:
    prefix_bytes = SIGNED_DATA_PREFIX.encode("utf-8")
    return prefix_bytes + noise_static_pubkey.to_bytes()


def make_handshake_payload_sig(
    id_privkey: PrivateKey, noise_static_pubkey: PublicKey
) -> bytes:
    data = make_data_to_be_signed(noise_static_pubkey)
    logger.debug(f"make_handshake_payload_sig: signing data length: {len(data)}")
    logger.debug(f"make_handshake_payload_sig: signing data hex: {data.hex()}")
    return id_privkey.sign(data)


def verify_handshake_payload_sig(
    payload: NoiseHandshakePayload, noise_static_pubkey: PublicKey
) -> bool:
    """
    Verify if the signature
        1. is composed of the data `SIGNED_DATA_PREFIX`++`noise_static_pubkey` and
        2. signed by the private key corresponding to `id_pubkey`
    """
    expected_data = make_data_to_be_signed(noise_static_pubkey)
    logger.debug(
        f"verify_handshake_payload_sig: payload.id_pubkey type: "
        f"{type(payload.id_pubkey)}"
    )
    logger.debug(
        f"verify_handshake_payload_sig: noise_static_pubkey type: "
        f"{type(noise_static_pubkey)}"
    )
    logger.debug(
        f"verify_handshake_payload_sig: expected_data length: {len(expected_data)}"
    )
    logger.debug(
        f"verify_handshake_payload_sig: expected_data hex: {expected_data.hex()}"
    )
    logger.debug(
        f"verify_handshake_payload_sig: payload.id_sig length: {len(payload.id_sig)}"
    )
    try:
        result = payload.id_pubkey.verify(expected_data, payload.id_sig)
        logger.debug(f"verify_handshake_payload_sig: verification result: {result}")
        return result
    except Exception as e:
        logger.error(f"verify_handshake_payload_sig: verification exception: {e}")
        return False
