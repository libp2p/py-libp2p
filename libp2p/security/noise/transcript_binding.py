"""
Transcript-bound security protocol negotiation for the Noise handshakes.

multistream-select picks the connection encrypter in plaintext, before any
handshake runs, so an on-path attacker can strip a proposal or forge an ``na``
and push both peers onto a weaker protocol without either noticing. Nothing in
the Noise handshake detects that today: ``identity_sig`` covers only the string
``noise-libp2p-static-key:`` followed by the static public key, which is a
statement about a key rather than about a session.

This module lets each peer state, inside the encrypted handshake payload, the
ordered list of security protocols it has configured, signed together with the
Noise transcript hash ``h`` so the statement cannot be replayed from another
session. Both peers then recompute what the negotiation should have produced::

    expected(dialer_offered, listener_supported) =
        the first p in dialer_offered that also appears in listener_supported

and compare it against the protocol they are actually running. The selected
protocol never goes on the wire, because each peer already knows which one it
is running.

Two bindings are implemented so their cost can be compared:

``extension``
    A separate ``transcript_sig`` field in ``NoiseExtensions`` over
    ``b"noise-libp2p-transcript:" || h || canonical(protocols)``. Unknown
    protobuf fields are ignored by older peers, so this is wire compatible in
    both directions and can be deployed incrementally.

``identity``
    The binding folded into ``identity_sig``, which then covers
    ``b"noise-libp2p-static-key:" || s_pub || h || canonical(protocols)``. One
    signature instead of two, but every libp2p peer verifies ``identity_sig``,
    so both ends must be configured the same way.

Under ``extension``, a peer that sends no binding at all is never treated as an
attack, in any mode: that is indistinguishable from talking to an older
implementation.

``identity`` does not behave that way, and ``mode`` does not change it. The
protocol list is inside ``identity_sig``, so a peer that sends no list signed a
different message and the handshake fails during signature verification, before
any mode is consulted. Selecting ``identity`` is therefore a flag day: such a
peer cannot connect to a stock libp2p peer, nor to a peer configured with
``extension``. Falling back to the unbound form on failure is deliberately not
offered, because that would let an attacker strip the binding at will. Deploying
``identity`` means giving it its own protocol identifier.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import logging
import struct
from typing import TYPE_CHECKING, Literal

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)

from .exceptions import (
    SecurityProtocolDowngrade,
)

if TYPE_CHECKING:
    from .messages import NoiseExtensions

logger = logging.getLogger(__name__)

#: Domain separator for the ``extension`` variant signature.
TRANSCRIPT_SIG_PREFIX = b"noise-libp2p-transcript:"

#: Upper bound on a single protocol identifier, so the uint16 length prefix in
#: the canonical encoding cannot overflow.
MAX_PROTOCOL_LENGTH = 0xFFFF

#: Upper bound on how many protocols a peer may claim. Verification cost is
#: linear in the encoded length, and no peer has a legitimate reason to
#: configure hundreds of connection encrypters.
MAX_PROTOCOLS = 32

#: Upper bound on the canonical encoding as a whole. The two limits above
#: allow about 2 MiB, far past the 65535-byte Noise message the list has to
#: travel in, so without this an oversized local config would surface as a
#: framing error mid-handshake rather than a clear error at construction.
MAX_ENCODED_PROTOCOLS_LENGTH = 4096

#: How strictly a peer treats the binding.
#:
#: ``off`` does not send the field and does not check it, ``warn`` sends the
#: field and logs a mismatch, ``enforce`` sends the field and aborts the
#: handshake on a mismatch.
#:
#: ``warn`` softens only that negotiation mismatch. A binding that is present
#: but malformed or unverifiable (a bad signature, one field without the other,
#: an over-long list) aborts the handshake in every mode, because it is not
#: what an older peer sends and it cannot be relied on to say anything.
TranscriptBindingMode = Literal["off", "warn", "enforce"]

#: Which of the two bindings is in use. See the module docstring.
TranscriptBindingVariant = Literal["extension", "identity"]

DEFAULT_MODE: TranscriptBindingMode = "enforce"
DEFAULT_VARIANT: TranscriptBindingVariant = "extension"


def canonical_protocols(protocols: Sequence[str]) -> bytes:
    """
    Encode a protocol list unambiguously for signing.

    Each identifier becomes a big-endian ``uint16`` length followed by its
    UTF-8 bytes, concatenated in the peer's own preference order. The order is
    significant and is never sorted, because the dialer's order is what decides
    the negotiation outcome.

    The length prefixes matter. Plain concatenation would let ``['ab', 'c']``
    and ``['a', 'bc']`` produce the same bytes, so an attacker could substitute
    one list for another under a signature that is valid for both.

    Args:
        protocols: Protocol identifiers in this peer's preference order.

    Returns:
        bytes: The canonical encoding of the list.

    Raises:
        ValueError: If the list or one of its identifiers is too long.

    """
    if len(protocols) > MAX_PROTOCOLS:
        raise ValueError(
            f"too many security protocols: {len(protocols)} > {MAX_PROTOCOLS}"
        )

    parts: list[bytes] = []
    for protocol in protocols:
        encoded = protocol.encode("utf-8")
        if len(encoded) > MAX_PROTOCOL_LENGTH:
            raise ValueError(
                f"security protocol identifier is too long: {len(encoded)} bytes"
            )
        parts.append(struct.pack(">H", len(encoded)))
        parts.append(encoded)

    canonical = b"".join(parts)
    if len(canonical) > MAX_ENCODED_PROTOCOLS_LENGTH:
        raise ValueError(
            f"encoded security protocol list is too long: {len(canonical)} "
            f"> {MAX_ENCODED_PROTOCOLS_LENGTH} bytes"
        )
    return canonical


def transcript_signature_payload(
    payload_hash: bytes, protocols: Sequence[str]
) -> bytes:
    """
    Build the bytes signed by the ``extension`` variant.

    ``payload_hash`` is the Noise transcript hash the handshake payload is
    encrypted under. Both peers hold the same value for a given payload, which
    is the standard Noise transcript property, so no extra round trip is needed
    to agree on what was signed.

    Args:
        payload_hash: The Noise ``h`` value the payload is encrypted under.
        protocols: Protocol identifiers in this peer's preference order.

    Returns:
        bytes: The data to sign or verify.

    """
    return TRANSCRIPT_SIG_PREFIX + payload_hash + canonical_protocols(protocols)


def sign_transcript_binding(
    id_privkey: PrivateKey, payload_hash: bytes, protocols: Sequence[str]
) -> bytes:
    """
    Sign this peer's protocol list under the current transcript hash.

    Args:
        id_privkey: The libp2p identity private key.
        payload_hash: The Noise ``h`` value the payload is encrypted under.
        protocols: Protocol identifiers in this peer's preference order.

    Returns:
        bytes: The ``transcript_sig`` extension field.

    """
    return id_privkey.sign(transcript_signature_payload(payload_hash, protocols))


def verify_transcript_binding(
    id_pubkey: PublicKey,
    payload_hash: bytes,
    protocols: Sequence[str],
    signature: bytes,
) -> bool:
    """
    Verify a remote peer's ``transcript_sig`` against the list it sent.

    A tampered list fails here, because the signature covers the canonical
    encoding of the list as well as the transcript hash.

    Args:
        id_pubkey: The remote peer's libp2p identity public key.
        payload_hash: The Noise ``h`` value the payload was encrypted under.
        protocols: The protocol list exactly as received.
        signature: The ``transcript_sig`` extension field as received.

    Returns:
        bool: True if the signature is valid.

    """
    try:
        expected = transcript_signature_payload(payload_hash, protocols)
    except ValueError as exc:
        logger.debug("transcript binding rejected: %s", exc)
        return False

    try:
        return id_pubkey.verify(expected, signature)
    except Exception as exc:
        logger.debug("transcript binding signature verification failed: %s", exc)
        return False


@dataclass(frozen=True)
class IdentityBinding:
    """
    The session binding the ``identity`` variant folds into ``identity_sig``.

    Carried separately from :class:`TranscriptBindingConfig` because a verifier
    has to fold in the protocol list exactly as the remote peer sent it, not
    the one it has configured itself.
    """

    #: The Noise ``h`` value the handshake payload is encrypted under.
    payload_hash: bytes
    #: The protocol list, in the order it is signed.
    protocols: tuple[str, ...]

    def suffix(self) -> bytes:
        """
        The bytes appended after the static public key in the signed data.

        Returns:
            bytes: ``h`` followed by the canonical encoding of the list.

        """
        return self.payload_hash + canonical_protocols(self.protocols)


def expected_protocol(
    dialer_offered: Sequence[str], listener_supported: Sequence[str]
) -> str | None:
    """
    Compute what multistream-select should have selected.

    That is the dialer's most preferred protocol that the listener also
    supports. Both peers evaluate this over the same two lists once the
    payloads have been exchanged, so both reach the same answer without either
    sending the answer.

    Args:
        dialer_offered: The dialer's list, in its preference order.
        listener_supported: The listener's list.

    Returns:
        str | None: The protocol that should have been negotiated, or None when
        the two lists have nothing in common.

    """
    supported = set(listener_supported)
    for protocol in dialer_offered:
        if protocol in supported:
            return protocol
    return None


@dataclass(frozen=True)
class TranscriptBindingConfig:
    """
    Everything a handshake needs in order to apply transcript binding.

    Assembled once by the secure transport and threaded through to the pattern.
    Passing ``None`` instead of a config anywhere this is optional is the same
    as ``mode="off"``.
    """

    #: The security protocols this peer has configured, in preference order.
    security_protocols: tuple[str, ...]
    #: The protocol identifier this handshake is running under.
    actual_protocol: str
    mode: TranscriptBindingMode = DEFAULT_MODE
    variant: TranscriptBindingVariant = DEFAULT_VARIANT

    def __post_init__(self) -> None:
        if self.actual_protocol not in self.security_protocols:
            raise ValueError(
                "security_protocols must include this transport's own protocol "
                f"{self.actual_protocol}, got {list(self.security_protocols)}"
            )
        # Fail at construction rather than mid-handshake if the list cannot be
        # encoded at all.
        canonical_protocols(self.security_protocols)

    @property
    def enabled(self) -> bool:
        """Whether this peer sends and checks the binding."""
        return self.mode != "off"


def is_enabled(config: TranscriptBindingConfig | None) -> bool:
    """
    Whether ``config`` asks for the binding to be sent and checked.

    Args:
        config: The transport's configuration, or None when unconfigured.

    Returns:
        bool: True if the binding is active.

    """
    return config is not None and config.enabled


def has_transcript_binding(
    extensions: "NoiseExtensions | None",
    variant: TranscriptBindingVariant = DEFAULT_VARIANT,
) -> bool:
    """
    Whether a received payload carries a binding this peer can rely on.

    A peer that omits it is an older peer, not an attacker, so the caller
    treats False as "nothing to check" rather than as a failure.

    Under ``extension`` the list is only meaningful alongside its own
    signature. Under ``identity`` the list alone is enough, because it is
    covered by ``identity_sig``: by the time this is consulted that signature
    has been verified over the list as received, so a peer that sent a list it
    did not sign never gets this far.

    Args:
        extensions: The extensions from the remote handshake payload.
        variant: The binding variant this peer is configured for.

    Returns:
        bool: True if the remote peer's protocol list can be relied on.

    """
    if extensions is None or not extensions.security_protocols:
        return False
    if variant == "extension":
        return bool(extensions.transcript_sig)
    return True


def is_partial_binding(extensions: "NoiseExtensions | None") -> bool:
    """
    Whether an ``extension``-variant binding is half present.

    An older peer sends neither ``security_protocols`` nor ``transcript_sig``.
    One without the other is malformed rather than old, and since both travel
    under the handshake AEAD an on-path attacker cannot produce it either, so
    the caller rejects it instead of treating it as "no binding".

    Args:
        extensions: The extensions from the remote handshake payload.

    Returns:
        bool: True if exactly one of the two fields is present.

    """
    if extensions is None:
        return False
    return bool(extensions.security_protocols) != bool(extensions.transcript_sig)


def check_negotiation(
    config: TranscriptBindingConfig | None,
    *,
    is_initiator: bool,
    remote_extensions: "NoiseExtensions | None",
) -> None:
    """
    Compare the negotiated protocol against what the two signed offers imply.

    The signature over ``remote_extensions`` must already have been verified
    against the remote identity key before this is called: an unverified list
    is attacker-controlled and checking it proves nothing.

    Args:
        config: This peer's configuration, or None when unconfigured.
        is_initiator: True if this peer dialled, so its own list is the dialer's.
        remote_extensions: The verified extensions from the remote payload.

    Raises:
        SecurityProtocolDowngrade: In ``enforce`` mode, when the negotiated
        protocol is not the one the two offers imply.

    """
    if config is None or config.mode == "off":
        return

    if remote_extensions is None or not has_transcript_binding(
        remote_extensions, config.variant
    ):
        logger.debug("remote peer sent no transcript binding, skipping check")
        return

    remote_protocols = tuple(remote_extensions.security_protocols)
    local_protocols = config.security_protocols

    if is_initiator:
        dialer_offered, listener_supported = local_protocols, remote_protocols
    else:
        dialer_offered, listener_supported = remote_protocols, local_protocols

    expected = expected_protocol(dialer_offered, listener_supported)
    if expected == config.actual_protocol:
        return

    if expected is None:
        detail = (
            "the two offers have no protocol in common, yet "
            f"{config.actual_protocol} was negotiated"
        )
    else:
        detail = (
            f"{expected} should have been negotiated, but this session is "
            f"running {config.actual_protocol}"
        )

    message = (
        f"security protocol downgrade detected: {detail} "
        f"(dialer offered {list(dialer_offered)}, "
        f"listener supports {list(listener_supported)})"
    )

    if config.mode == "warn":
        logger.warning(message)
        return

    raise SecurityProtocolDowngrade(message)
