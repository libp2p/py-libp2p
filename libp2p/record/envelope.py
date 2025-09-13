from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.serialization import deserialize_public_key
from typing import Optional, Tuple

from libp2p.record.record import Record, unmarshal_record_payload
import threading
import libp2p.record.pb.envelope_pb2 as pb
from libp2p.record.exceptions import (
    ErrEmptyDomain,
    ErrEmptyPayloadType,
    ErrInvalidSignature
)

class Envelope:
    public_key: PublicKey
    payload_type: bytes
    raw_payload: bytes
    signature: bytes

    def __init__(self, public_key: PublicKey, payload_type: bytes, raw_payload: bytes, signature: bytes):
        self.public_key = public_key
        self.payload_type = payload_type
        self.raw_payload = raw_payload
        self.signature = signature 

        self._cached_record: Optional[Record] = None
        self._unmarshal_error: Optional[Exception] = None
        self._unmarshal_lock = threading.Lock()
        self._record_initialized: bool = False

    def marshal(self) -> bytes:
        key = self.public_key.serialize_to_protobuf()
        msg = pb.Envelope(
            public_key=key,
            payload_type=self.payload_type,
            payload=self.raw_payload,
            signature=self.signature
        )
        return msg.SerializeToString()
    
    @classmethod
    def unmarshal_envelope(cls, data: bytes) -> "Envelope":
        msg = pb.Envelope()
        msg.ParseFromString(data)

        key = deserialize_public_key(msg.public_key.SerializePartialToString())
        return cls(
            public_key=key,
            payload_type=msg.payload_type,
            raw_payload=msg.payload,
            signature=msg.signature
        )

    def equal(self, other: "Envelope") -> bool:
        if other is None:
            return False
        return (
            self.public_key.__eq__(other.public_key) and
            self.payload_type == other.payload_type and
            self.raw_payload == other.raw_payload and
            self.signature == other.signature
        )

    def record(self) -> Record:
        """Return the unmarshalled Record, caching on first access."""
        with self._unmarshal_lock:
            if self._cached_record is not None:
                return self._cached_record
            try:
                self._cached_record = unmarshal_record_payload(
                    payload_type=self.payload_type, 
                    payload_bytes=self.raw_payload
                )
            except Exception as e:
                self._unmarshal_error = e
                raise
            return self._cached_record

    def validate(self, domain: str) -> bool:
        if not domain:
            raise ErrEmptyDomain("domain cannot be empty")
        if not self.payload_type:
            raise ErrEmptyPayloadType("payload_type cannot be empty")
        
        try:
            unsigned = make_unsigned(domain=domain, payload_type=self.payload_type, payload=self.raw_payload)
            valid = self.public_key.verify(unsigned, self.signature)
            if not valid:
                raise ErrInvalidSignature("invalid signature or domain")
        except Exception as e:
            raise e
        return True


def seal(rec: Record, private_key: PrivateKey) -> Envelope:
    payload = rec.marshal_record()
    payload_type = rec.codec()
    domain = rec.domain()

    if not domain:
        raise ErrEmptyDomain()
    if not payload_type:
        raise ErrEmptyPayloadType()

    unsigned = make_unsigned(domain=domain, payload_type=payload_type, payload=payload)
    sig = private_key.sign(unsigned)
    return Envelope(
        public_key=private_key.get_public_key(),
        payload_type=payload_type,
        raw_payload=payload,
        signature=sig
    )


def consume_envelope(data: bytes, domain: str) -> Tuple[Envelope, Record]:
    msg = Envelope.unmarshal_envelope(data)
    msg.validate(domain)
    rec = msg.record()
    return msg, rec

def encode_uvarint(value: int) -> bytes:
    """Encode an int as protobuf-style unsigned varint."""
    buf = bytearray()
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value)
    return bytes(buf)


def make_unsigned(domain: str, payload_type: bytes, payload: bytes) -> bytes:
    fields = [domain.encode("utf-8"), payload_type, payload]
    b = bytearray()
    for f in fields:
        b.extend(encode_uvarint(len(f)))
        b.extend(f)
    return bytes(b)
