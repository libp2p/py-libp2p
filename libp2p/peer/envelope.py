from typing import Any, cast

import multiaddr
from multicodec import Code, get_codec, get_prefix
from multicodec.code_table import LIBP2P_PEER_RECORD

from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.rsa import RSAPublicKey
from libp2p.crypto.secp256k1 import Secp256k1PublicKey
import libp2p.peer.pb.crypto_pb2 as cryto_pb
import libp2p.peer.pb.envelope_pb2 as pb
import libp2p.peer.pb.peer_record_pb2 as record_pb
from libp2p.peer.peer_record import (
    PeerRecord,
    peer_record_from_protobuf,
    unmarshal_record,
)
from libp2p.utils.varint import encode_uvarint

ENVELOPE_DOMAIN = "libp2p-peer-record"
# Multicodec-based codec for peer records
PEER_RECORD_CODE: Code = LIBP2P_PEER_RECORD
PEER_RECORD_CODEC: bytes = get_prefix(str(PEER_RECORD_CODE))


class Envelope:
    """
    A signed wrapper around a serialized libp2p record.

    Envelopes are cryptographically signed by the author's private key
    and are scoped to a specific 'domain' to prevent cross-protocol replay.

    Attributes:
        public_key: The public key that can verify the envelope's signature.
        payload_type: A multicodec code identifying the type of payload inside.
        raw_payload: The raw serialized record data.
        signature: Signature over the domain-scoped payload content.

    """

    public_key: PublicKey
    payload_type_code: Code
    raw_payload: bytes
    signature: bytes

    _cached_record: PeerRecord | None = None
    _unmarshal_error: Exception | None = None

    def __init__(
        self,
        public_key: PublicKey,
        payload_type: Code | str | bytes,
        raw_payload: bytes,
        signature: bytes,
    ):
        self.public_key = public_key

        # Normalise payload_type to a Code instance
        if isinstance(payload_type, bytes):
            try:
                codec_name = get_codec(payload_type)
                self.payload_type_code = Code.from_string(codec_name)
            except Exception as e:
                raise ValueError(f"Invalid codec: {e}")
        elif isinstance(payload_type, str):
            try:
                self.payload_type_code = Code.from_string(payload_type)
            except Exception as e:
                raise ValueError(f"Invalid codec: {e}")
        else:
            self.payload_type_code = payload_type

        self.raw_payload = raw_payload
        self.signature = signature

    @property
    def payload_type(self) -> bytes:
        """Return the multicodec-prefixed payload type."""
        return get_prefix(str(self.payload_type_code))

    def marshal_envelope(self) -> bytes:
        """
        Serialize this Envelope into its protobuf wire format.

        Converts all envelope fields into a `pb.Envelope` protobuf message
        and returns the serialized bytes.

        :return: Serialized envelope as bytes.
        """
        pb_env = pb.Envelope(
            public_key=pub_key_to_protobuf(self.public_key),
            payload_type=self.payload_type,
            payload=self.raw_payload,
            signature=self.signature,
        )
        return pb_env.SerializeToString()

    def validate(self, domain: str) -> None:
        """
        Verify the envelope's signature within the given domain scope.

        This ensures that the envelope has not been tampered with
        and was signed under the correct usage context.

        :param domain: Domain string that contextualizes the signature.
        :raises ValueError: If the signature is invalid.
        """
        unsigned = make_unsigned(domain, self.payload_type, self.raw_payload)
        if not self.public_key.verify(unsigned, self.signature):
            raise ValueError("Invalid envelope signature")

    def record(self) -> PeerRecord:
        """
        Lazily decode and return the embedded PeerRecord.

        This method unmarshals the payload bytes into a `PeerRecord` instance,
        using the registered codec to identify the type. The decoded result
        is cached for future use.

        :return: Decoded PeerRecord object.
        :raises Exception: If decoding fails or payload type is unsupported.
        """
        if self._cached_record is not None:
            return self._cached_record

        try:
            if self.payload_type_code != PEER_RECORD_CODE:
                raise ValueError(
                    f"Unsupported payload type in envelope: "
                    f"{self.payload_type_code.name}"
                )
            msg = record_pb.PeerRecord()
            msg.ParseFromString(self.raw_payload)

            self._cached_record = peer_record_from_protobuf(msg)
            return self._cached_record
        except Exception as e:
            self._unmarshal_error = e
            raise

    def equal(self, other: Any) -> bool:
        """
        Compare this Envelope with another for structural equality.

        Two envelopes are considered equal if:
        - They have the same public key
        - The payload type and payload bytes match
        - Their signatures are identical

        :param other: Another object to compare.
        :return: True if equal, False otherwise.
        """
        if isinstance(other, Envelope):
            return (
                self.public_key.__eq__(other.public_key)
                and self.payload_type_code == other.payload_type_code
                and self.signature == other.signature
                and self.raw_payload == other.raw_payload
            )
        return False

    def _env_addrs_set(self) -> set[multiaddr.Multiaddr]:
        return {b for b in self.record().addrs}


def pub_key_to_protobuf(pub_key: PublicKey) -> cryto_pb.PublicKey:
    """
    Convert a Python PublicKey object to its protobuf equivalent.

    :param pub_key: A libp2p-compatible PublicKey instance.
    :return: Serialized protobuf PublicKey message.
    """
    internal_key_type = pub_key.get_type()
    key_type = cast(cryto_pb.KeyType, internal_key_type.value)
    data = pub_key.to_bytes()
    protobuf_key = cryto_pb.PublicKey(Type=key_type, Data=data)
    return protobuf_key


def pub_key_from_protobuf(pb_key: cryto_pb.PublicKey) -> PublicKey:
    """
    Parse a protobuf PublicKey message into a native libp2p PublicKey.

    Supports Ed25519, RSA, and Secp256k1 key types.

    :param pb_key: Protobuf representation of a public key.
    :return: Parsed PublicKey object.
    :raises ValueError: If the key type is unrecognized.
    """
    if pb_key.Type == cryto_pb.KeyType.Ed25519:
        return Ed25519PublicKey.from_bytes(pb_key.Data)
    elif pb_key.Type == cryto_pb.KeyType.RSA:
        return RSAPublicKey.from_bytes(pb_key.Data)
    elif pb_key.Type == cryto_pb.KeyType.Secp256k1:
        return Secp256k1PublicKey.from_bytes(pb_key.Data)
    # libp2p.crypto.ecdsa not implemented
    else:
        raise ValueError(f"Unknown key type: {pb_key.Type}")


def seal_record(record: PeerRecord, private_key: PrivateKey) -> Envelope:
    """
    Create and sign a new Envelope from a PeerRecord.

    The record is serialized and signed in the scope of its domain and codec.
    The result is a self-contained, verifiable Envelope.

    :param record: A PeerRecord to encapsulate.
    :param private_key: The signer's private key.
    :return: A signed Envelope instance.
    """
    payload = record.marshal_record()

    unsigned = make_unsigned(record.domain(), record.codec(), payload)
    signature = private_key.sign(unsigned)

    return Envelope(
        public_key=private_key.get_public_key(),
        payload_type=PEER_RECORD_CODE,
        raw_payload=payload,
        signature=signature,
    )


def consume_envelope(data: bytes, domain: str) -> tuple[Envelope, PeerRecord]:
    """
    Parse, validate, and decode an Envelope from bytes.

    Validates the envelope's signature using the given domain and decodes
    the inner payload into a PeerRecord.

    :param data: Serialized envelope bytes.
    :param domain: Domain string to verify signature against.
    :return: Tuple of (Envelope, PeerRecord).
    :raises ValueError: If signature validation or decoding fails.
    """
    env = unmarshal_envelope(data)
    env.validate(domain)
    record = env.record()
    return env, record


def unmarshal_envelope(data: bytes) -> Envelope:
    """
    Deserialize an Envelope from its wire format.

    This parses the protobuf fields without verifying the signature.

    :param data: Serialized envelope bytes.
    :return: Parsed Envelope object.
    :raises DecodeError: If protobuf parsing fails.
    """
    pb_env = pb.Envelope()
    pb_env.ParseFromString(data)
    pk = pub_key_from_protobuf(pb_env.public_key)

    return Envelope(
        public_key=pk,
        payload_type=pb_env.payload_type,
        raw_payload=pb_env.payload,
        signature=pb_env.signature,
    )


def make_unsigned(domain: str, payload_type: bytes, payload: bytes) -> bytes:
    """
    Build a byte buffer to be signed for an Envelope.

    The unsigned byte structure is:
        varint(len(domain)) || domain ||
        varint(len(payload_type)) || payload_type ||
        varint(len(payload)) || payload

    This is the exact input used during signing and verification.

    :param domain: Domain string for signature scoping.
    :param payload_type: Identifier for the type of payload.
    :param payload: Raw serialized payload bytes.
    :return: Byte buffer to be signed or verified.
    """
    fields = [domain.encode(), payload_type, payload]
    buf = bytearray()

    for field in fields:
        buf.extend(encode_uvarint(len(field)))
        buf.extend(field)

    return bytes(buf)


def debug_dump_envelope(env: Envelope) -> None:
    print("\n=== Envelope ===")
    print(f"Payload Type: {env.payload_type!r}")
    print(f"Signature: {env.signature.hex()} ({len(env.signature)} bytes)")
    print(f"Raw Payload: {env.raw_payload.hex()} ({len(env.raw_payload)} bytes)")

    try:
        peer_record = unmarshal_record(env.raw_payload)
        print("\n=== Parsed PeerRecord ===")
        print(peer_record)
    except Exception as e:
        print("Failed to parse PeerRecord:", e)
