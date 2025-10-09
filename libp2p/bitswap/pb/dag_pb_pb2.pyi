from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PBLink(_message.Message):
    __slots__ = ("Hash", "Name", "Tsize")
    HASH_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TSIZE_FIELD_NUMBER: _ClassVar[int]
    Hash: bytes
    Name: str
    Tsize: int
    def __init__(self, Hash: _Optional[bytes] = ..., Name: _Optional[str] = ..., Tsize: _Optional[int] = ...) -> None: ...

class PBNode(_message.Message):
    __slots__ = ("Links", "Data")
    LINKS_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    Links: _containers.RepeatedCompositeFieldContainer[PBLink]
    Data: bytes
    def __init__(self, Links: _Optional[_Iterable[_Union[PBLink, _Mapping]]] = ..., Data: _Optional[bytes] = ...) -> None: ...
