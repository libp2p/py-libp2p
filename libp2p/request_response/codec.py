from __future__ import annotations

import json
from typing import Any, Protocol, TypeVar, runtime_checkable

ReqT = TypeVar("ReqT")
RespT = TypeVar("RespT")


@runtime_checkable
class RequestResponseCodec(Protocol[ReqT, RespT]):
    def encode_request(self, request: ReqT) -> bytes: ...

    def decode_request(self, payload: bytes) -> ReqT: ...

    def encode_response(self, response: RespT) -> bytes: ...

    def decode_response(self, payload: bytes) -> RespT: ...


class BytesCodec(RequestResponseCodec[bytes, bytes]):
    """Pass-through codec for raw bytes payloads."""

    def encode_request(self, request: bytes) -> bytes:
        return bytes(request)

    def decode_request(self, payload: bytes) -> bytes:
        return bytes(payload)

    def encode_response(self, response: bytes) -> bytes:
        return bytes(response)

    def decode_response(self, payload: bytes) -> bytes:
        return bytes(payload)


class JSONCodec(RequestResponseCodec[Any, Any]):
    """Codec for JSON-serializable Python values."""

    def encode_request(self, request: Any) -> bytes:
        return json.dumps(request).encode("utf-8")

    def decode_request(self, payload: bytes) -> Any:
        return json.loads(payload.decode("utf-8"))

    def encode_response(self, response: Any) -> bytes:
        return json.dumps(response).encode("utf-8")

    def decode_response(self, payload: bytes) -> Any:
        return json.loads(payload.decode("utf-8"))
