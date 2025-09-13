from abc import ABC, abstractmethod
from typing import Dict, Type, Optional

# Registry of payload_type (bytes) -> Record class
_payload_type_registry: Dict[bytes, Type["Record"]] = {}

class Record(ABC):
    """
    Record represents a data type that can be used as the payload of an Envelope.
    """

    @abstractmethod
    def domain(self) -> str:
        """The signature domain (unique string for this record type)."""
        pass

    @abstractmethod
    def codec(self) -> bytes:
        """Binary identifier (payload type)."""
        pass

    @abstractmethod
    def marshal_record(self) -> bytes:
        """Serialize the record into bytes."""
        pass

    @abstractmethod
    def unmarshal_record(self, data: bytes) -> None:
        """Deserialize bytes into this record instance."""
        pass


def register_type(prototype: Record) -> None:
    """
    Register a record type by its codec.
    Should be called in module init where the Record is defined just like the Go version.
    """
    codec = prototype.codec()
    if not isinstance(codec, (bytes, bytearray)):
        raise TypeError("codec() must return bytes")
    _payload_type_registry[bytes(codec)] = type(prototype)


def blank_record_for_payload_type(payload_type: bytes) -> Record:
    """
    Create a blank record for the given payload type.
    """
    cls = _payload_type_registry.get(payload_type)
    if cls is None:
        raise ValueError("payload type is not registered")
    return cls()


def unmarshal_record_payload(payload_type: bytes, payload_bytes: bytes) -> Record:
    """
    Given a payload type and bytes, return a fully unmarshalled Record.
    """
    rec = blank_record_for_payload_type(payload_type)
    rec.unmarshal_record(payload_bytes)
    return rec

    