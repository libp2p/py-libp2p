from typing import Any, List, Optional, Union

class Message:
    type: int
    dial: Any
    dial_response: Any
    
    def ParseFromString(self, data: bytes) -> None: ...
    def SerializeToString(self) -> bytes: ...
    @staticmethod
    def FromString(data: bytes) -> 'Message': ...

class DialRequest:
    peers: List[Any]
    
    def ParseFromString(self, data: bytes) -> None: ...
    def SerializeToString(self) -> bytes: ...
    @staticmethod
    def FromString(data: bytes) -> 'DialRequest': ...

class DialResponse:
    status: int
    peers: List[Any]
    
    def ParseFromString(self, data: bytes) -> None: ...
    def SerializeToString(self) -> bytes: ...
    @staticmethod
    def FromString(data: bytes) -> 'DialResponse': ...

class PeerInfo:
    id: bytes
    addrs: List[bytes]
    success: bool
    
    def ParseFromString(self, data: bytes) -> None: ...
    def SerializeToString(self) -> bytes: ...
    @staticmethod
    def FromString(data: bytes) -> 'PeerInfo': ...

class Type:
    UNKNOWN: int
    DIAL: int
    DIAL_RESPONSE: int
    
    @staticmethod
    def Value(name: str) -> int: ...

class Status:
    OK: int
    E_DIAL_ERROR: int
    E_DIAL_REFUSED: int
    E_DIAL_FAILED: int
    E_INTERNAL_ERROR: int
    
    @staticmethod
    def Value(name: str) -> int: ... 