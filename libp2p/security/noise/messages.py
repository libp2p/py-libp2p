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
from .transcript_binding import (
    IdentityBinding,
    TranscriptBindingConfig,
    has_transcript_binding,
    is_enabled,
    is_partial_binding,
    sign_transcript_binding,
    verify_transcript_binding,
)

logger = logging.getLogger(__name__)

SIGNED_DATA_PREFIX = "noise-libp2p-static-key:"


@dataclass
class NoiseExtensions:
    """
    Noise protocol extensions for advanced features like WebTransport and early data.

    This class provides support for:
    - WebTransport certificate hashes for WebTransport support
    - Stream multiplexers supported by this peer (spec compliant)
    - A configured security protocol list, signed against this session
    - Early data payload for 0-RTT support (Python extension)
    """

    webtransport_certhashes: list[bytes] = field(default_factory=list)
    stream_muxers: list[str] = field(default_factory=list)
    security_protocols: list[str] = field(default_factory=list)
    transcript_sig: bytes = b""
    early_data: bytes | None = None

    def to_protobuf(self) -> noise_pb.NoiseExtensions:
        """
        Convert to protobuf message.

        Returns:
            noise_pb.NoiseExtensions: The protobuf message representation

        """
        ext = noise_pb.NoiseExtensions()
        ext.webtransport_certhashes.extend(self.webtransport_certhashes)
        ext.stream_muxers.extend(self.stream_muxers)  # type: ignore[attr-defined]
        ext.security_protocols.extend(self.security_protocols)
        if self.transcript_sig:
            ext.transcript_sig = self.transcript_sig
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
        if pb_ext.HasField("early_data"):
            early_data = pb_ext.early_data
        return cls(
            webtransport_certhashes=list(pb_ext.webtransport_certhashes),
            stream_muxers=list(pb_ext.stream_muxers),  # type: ignore[attr-defined]
            security_protocols=list(pb_ext.security_protocols),
            transcript_sig=pb_ext.transcript_sig,
            early_data=early_data,
        )

    def is_empty(self) -> bool:
        """
        Check if extensions are empty (no data).

        Returns:
            bool: True if no extensions data is present

        """
        return (
            not self.webtransport_certhashes
            and not self.stream_muxers
            and not self.security_protocols
            and not self.transcript_sig
            and self.early_data is None
        )

    def has_webtransport_certhashes(self) -> bool:
        """
        Check if WebTransport certificate hashes are present.

        Returns:
            bool: True if WebTransport certificate hashes are present

        """
        return bool(self.webtransport_certhashes)

    def has_stream_muxers(self) -> bool:
        """
        Check if stream multiplexers are present.

        Returns:
            bool: True if stream multiplexers are present

        """
        return bool(self.stream_muxers)

    def has_security_protocols(self) -> bool:
        """
        Check if a security protocol list is present.

        Returns:
            bool: True if the peer declared its configured protocols

        """
        return bool(self.security_protocols)

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
    - Optional extensions for advanced features like WebTransport and stream muxers
    """

    id_pubkey: PublicKey
    id_sig: bytes
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

        # Include extensions if present
        if self.extensions is not None:
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
        if msg.HasField("extensions"):
            extensions = NoiseExtensions.from_protobuf(msg.extensions)

        try:
            id_pubkey = deserialize_public_key(msg.identity_key)
        except Exception as e:
            raise ValueError(f"Failed to deserialize public key: {e}")

        return cls(
            id_pubkey=id_pubkey,
            id_sig=msg.identity_sig,
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
        Check if early data is present in extensions.

        Returns:
            bool: True if early data is present

        """
        return self.extensions is not None and self.extensions.has_early_data()

    def get_early_data(self) -> bytes | None:
        """
        Get early data from extensions.

        Returns:
            bytes | None: The early data if present

        """
        if self.extensions is not None and self.extensions.has_early_data():
            return self.extensions.early_data
        return None


def make_data_to_be_signed(
    noise_static_pubkey: PublicKey, binding: IdentityBinding | None = None
) -> bytes:
    """
    Build the data covered by ``identity_sig``.

    Without a binding this is the spec's ``SIGNED_DATA_PREFIX`` followed by the
    Noise static public key. Under the ``identity`` transcript-binding variant
    the session's transcript hash and the canonical protocol list are appended,
    so one signature covers both the key and the negotiation.

    Args:
        noise_static_pubkey: The Noise static public key being attested.
        binding: The session binding, or None for the unbound form.

    Returns:
        bytes: The data to sign or verify.

    """
    prefix_bytes = SIGNED_DATA_PREFIX.encode("utf-8")
    data = prefix_bytes + noise_static_pubkey.to_bytes()
    if binding is not None:
        data += binding.suffix()
    return data


def make_handshake_payload_sig(
    id_privkey: PrivateKey,
    noise_static_pubkey: PublicKey,
    binding: IdentityBinding | None = None,
) -> bytes:
    data = make_data_to_be_signed(noise_static_pubkey, binding)
    logger.debug(f"make_handshake_payload_sig: signing data length: {len(data)}")
    logger.debug(f"make_handshake_payload_sig: signing data hex: {data.hex()}")
    return id_privkey.sign(data)


def build_handshake_payload(
    id_privkey: PrivateKey,
    noise_static_pubkey: PublicKey,
    extensions: NoiseExtensions | None = None,
    config: TranscriptBindingConfig | None = None,
    payload_hash: bytes | None = None,
) -> NoiseHandshakePayload:
    """
    Build a handshake payload, optionally bound to this session's transcript.

    ``payload_hash`` is the Noise ``h`` value this payload will be encrypted
    under, which is why the payload has to be built after the message tokens
    have run rather than up front. When binding is off, or no hash is
    available, the payload is exactly what it was before this feature existed.

    Args:
        id_privkey: The libp2p identity private key.
        noise_static_pubkey: The Noise static public key to attest.
        extensions: Extensions to carry, or None.
        config: The transcript-binding configuration, or None when unconfigured.
        payload_hash: The Noise ``h`` value, or None when binding is off.

    Returns:
        NoiseHandshakePayload: The payload, ready to serialize and encrypt.

    """
    if not is_enabled(config) or payload_hash is None:
        return NoiseHandshakePayload(
            id_privkey.get_public_key(),
            make_handshake_payload_sig(id_privkey, noise_static_pubkey),
            extensions=extensions,
        )

    # narrowed by is_enabled(), which is False for None
    assert config is not None
    protocols = config.security_protocols
    identity_binding: IdentityBinding | None = None
    transcript_sig = b""

    if config.variant == "identity":
        identity_binding = IdentityBinding(payload_hash, protocols)
    else:
        transcript_sig = sign_transcript_binding(id_privkey, payload_hash, protocols)

    bound_extensions = NoiseExtensions(
        webtransport_certhashes=(
            list(extensions.webtransport_certhashes) if extensions else []
        ),
        stream_muxers=list(extensions.stream_muxers) if extensions else [],
        security_protocols=list(protocols),
        transcript_sig=transcript_sig,
        early_data=extensions.early_data if extensions else None,
    )

    return NoiseHandshakePayload(
        id_privkey.get_public_key(),
        make_handshake_payload_sig(id_privkey, noise_static_pubkey, identity_binding),
        extensions=bound_extensions,
    )


def verify_handshake_payload_sig(
    payload: NoiseHandshakePayload,
    noise_static_pubkey: PublicKey,
    config: TranscriptBindingConfig | None = None,
    payload_hash: bytes | None = None,
) -> bool:
    """
    Verify if the signature
        1. is composed of the data `SIGNED_DATA_PREFIX`++`noise_static_pubkey` and
        2. signed by the private key corresponding to `id_pubkey`

    When transcript binding is active the session binding is checked here too,
    because an unverified protocol list is attacker-controlled and comparing it
    against anything proves nothing. Under the ``extension`` variant that means
    a second signature check over ``transcript_sig``, skipped when the remote
    peer sent no binding at all. Under the ``identity`` variant the list as
    received is folded into the data ``identity_sig`` must cover, so a tampered
    list fails the existing check.

    Args:
        payload: The decoded remote handshake payload.
        noise_static_pubkey: The remote Noise static public key.
        config: This peer's transcript-binding configuration, or None.
        payload_hash: The Noise ``h`` value the payload was encrypted under.

    Returns:
        bool: True if every applicable signature is valid.

    """
    binding_active = is_enabled(config) and payload_hash is not None
    remote_extensions = payload.extensions
    remote_protocols = tuple(
        remote_extensions.security_protocols if remote_extensions else ()
    )

    identity_binding: IdentityBinding | None = None
    if binding_active and config is not None and config.variant == "identity":
        assert payload_hash is not None  # implied by binding_active
        identity_binding = IdentityBinding(payload_hash, remote_protocols)

    # The remote peer controls the protocol list, and canonical_protocols
    # rejects a list longer than MAX_PROTOCOLS by raising. Building the signed
    # data is therefore attacker-reachable and has to fail as a rejected
    # signature, not as an exception escaping a function documented to return
    # bool. The extension variant already rejects the same input this way.
    try:
        expected_data = make_data_to_be_signed(noise_static_pubkey, identity_binding)
    except ValueError as exc:
        logger.debug(f"verify_handshake_payload_sig: unusable protocol list: {exc}")
        return False

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
    except Exception as e:
        logger.error(f"verify_handshake_payload_sig: verification exception: {e}")
        return False

    if not result:
        return False

    # identity_sig has just been verified over the list as received. No honest
    # config yields an empty list, since it must name the transport's own
    # protocol, and accepting one would let the peer skip the downgrade check
    # under the variant that is meant to fail closed.
    if (
        binding_active
        and config is not None
        and config.variant == "identity"
        and not remote_protocols
    ):
        logger.error("verify_handshake_payload_sig: identity binding lists nothing")
        return False

    # An older peer sends neither field. One without the other is malformed
    # rather than old, and both travel under the handshake AEAD, so it is
    # rejected here, in every mode, instead of being read as "no binding".
    if (
        binding_active
        and config is not None
        and config.variant == "extension"
        and is_partial_binding(remote_extensions)
    ):
        logger.error("verify_handshake_payload_sig: partial transcript binding")
        return False

    # The extension variant carries its own signature. A peer that sends no
    # binding is an older peer rather than an attacker, so there is nothing to
    # check in that case; the downgrade check skips it too.
    if (
        binding_active
        and config is not None
        and config.variant == "extension"
        and remote_extensions is not None
        and has_transcript_binding(remote_extensions, "extension")
    ):
        assert payload_hash is not None  # implied by binding_active
        if not verify_transcript_binding(
            payload.id_pubkey,
            payload_hash,
            remote_protocols,
            remote_extensions.transcript_sig,
        ):
            logger.error("verify_handshake_payload_sig: invalid transcript binding")
            return False

    return True
