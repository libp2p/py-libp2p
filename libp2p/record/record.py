from __future__ import annotations
from curses import raw
import libp2p.record.pb.record_pb2 as pb
from typing import Optional, Union


class Record:
    """
    Record wraps the protobuf Record message and provides helper
    methods for marshalling, unmarshalling, and safe field access.
    """

    raw_record: pb.Record

    def __init__(
        self,
        key: Union[str, bytes],
        value: bytes,
        time_received: Optional[str] = None,
    ):
        if isinstance(key, str):
            key = key.encode("utf-8")

        self.raw_record = pb.Record(
            key=key,
            value=value,
            timeReceived=time_received or "",
        )

    @property
    def key(self) -> bytes:
        return self.raw_record.key

    @property
    def key_str(self) -> str:
        return self.raw_record.key.decode("utf-8")

    @property
    def value(self) -> bytes:
        return self.raw_record.value
    
    @property
    def value_str(self) -> str:
        return self.raw_record.value.decode("utf-8")

    @property
    def time_received(self) -> str:
        return self.raw_record.timeReceived


    def marshal(self) -> bytes:
        """Serialize the record to bytes."""
        return self.raw_record.SerializeToString()

    @classmethod
    def unmarshal(cls, data: bytes) -> Record:
        """Deserialize bytes into a Record instance."""
        msg = pb.Record()
        msg.ParseFromString(data)
        return cls(
            key=msg.key,
            value=msg.value,
            time_received=msg.timeReceived,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Record):
            return False
        return self.marshal() == other.marshal()

    def __repr__(self) -> str:
        return (
            f"<Record key={self.key!r} value={self.value!r} "
            f"timeReceived={self.time_received!r}>"
        )
