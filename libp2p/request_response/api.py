from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
import logging
from typing import Generic, TypeVar, cast

import trio

from libp2p.abc import IHost, INetStream
from libp2p.custom_types import TProtocol
from libp2p.host.exceptions import StreamFailure
from libp2p.io.exceptions import IncompleteReadError, MessageTooLarge
from libp2p.io.msgio import VarIntLengthMsgReadWriter
from libp2p.network.stream.exceptions import StreamEOF, StreamError, StreamReset
from libp2p.peer.id import ID
from libp2p.protocol_muxer.exceptions import (
    MultiselectClientError as MultiselectClientError,
    ProtocolNotSupportedError as MultiselectProtocolNotSupportedError,
)

from .codec import RequestResponseCodec
from .exceptions import (
    MessageTooLargeError,
    ProtocolNotSupportedError,
    RequestDecodeError,
    RequestEncodeError,
    RequestResponseError,
    RequestTimeoutError,
    RequestTransportError,
    ResponseDecodeError,
    ResponseEncodeError,
)

ReqT = TypeVar("ReqT")
RespT = TypeVar("RespT")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RequestContext:
    peer_id: ID
    protocol_id: TProtocol


@dataclass(frozen=True, slots=True)
class RequestResponseConfig:
    timeout: float = 10.0
    max_request_size: int = 1_048_576
    max_response_size: int = 10_485_760
    max_concurrent_inbound: int = 128

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        if self.max_request_size <= 0:
            raise ValueError("max_request_size must be greater than 0")
        if self.max_response_size <= 0:
            raise ValueError("max_response_size must be greater than 0")
        if self.max_concurrent_inbound <= 0:
            raise ValueError("max_concurrent_inbound must be greater than 0")


RequestHandler = Callable[[ReqT, RequestContext], Awaitable[RespT]]


@dataclass(slots=True)
class _HandlerRegistration(Generic[ReqT, RespT]):
    handler: RequestHandler[ReqT, RespT]
    codec: RequestResponseCodec[ReqT, RespT]
    config: RequestResponseConfig
    limiter: trio.Semaphore


class RequestResponse:
    """Safe, one-shot request/response helper on top of libp2p streams."""

    def __init__(self, host: IHost) -> None:
        self.host = host
        self._handlers: dict[TProtocol, _HandlerRegistration[object, object]] = {}

    def set_handler(
        self,
        protocol_id: TProtocol,
        handler: RequestHandler[ReqT, RespT],
        codec: RequestResponseCodec[ReqT, RespT],
        config: RequestResponseConfig | None = None,
    ) -> None:
        effective_config = config or RequestResponseConfig()
        registration = _HandlerRegistration(
            handler=cast(RequestHandler[object, object], handler),
            codec=cast(RequestResponseCodec[object, object], codec),
            config=effective_config,
            limiter=trio.Semaphore(effective_config.max_concurrent_inbound),
        )
        self._handlers[protocol_id] = registration
        self.host.set_stream_handler(
            protocol_id, self._build_stream_handler(protocol_id)
        )

    def remove_handler(self, protocol_id: TProtocol) -> None:
        self._handlers.pop(protocol_id, None)
        self.host.remove_stream_handler(protocol_id)

    async def send_request(
        self,
        peer_id: ID,
        protocol_ids: Sequence[TProtocol],
        request: ReqT,
        codec: RequestResponseCodec[ReqT, RespT],
        config: RequestResponseConfig | None = None,
    ) -> RespT:
        if not protocol_ids:
            raise ValueError("protocol_ids must not be empty")

        effective_config = config or RequestResponseConfig()
        request_payload = self._encode_request(codec, request)
        self._check_size(
            request_payload,
            effective_config.max_request_size,
            "request payload exceeds configured maximum",
        )

        stream: INetStream | None = None
        try:
            with trio.fail_after(effective_config.timeout):
                stream = await self.host.new_stream(peer_id, protocol_ids)
                await self._write_message(
                    stream, request_payload, effective_config.max_request_size
                )
                response_payload = await self._read_message(
                    stream, effective_config.max_response_size
                )
                response = self._decode_response(codec, response_payload)
        except trio.TooSlowError as error:
            await self._safe_reset(stream)
            raise RequestTimeoutError(
                f"request timed out after {effective_config.timeout} seconds"
            ) from error
        except MessageTooLargeError:
            await self._safe_reset(stream)
            raise
        except StreamFailure as error:
            raise self._map_stream_failure(error) from error
        except RequestResponseError:
            await self._safe_reset(stream)
            raise
        except (IncompleteReadError, StreamEOF, StreamError, StreamReset) as error:
            await self._safe_reset(stream)
            raise RequestTransportError(
                "request/response exchange failed while reading or writing the stream"
            ) from error
        except Exception as error:
            await self._safe_reset(stream)
            raise RequestTransportError(
                "request/response exchange failed due to an unexpected transport error"
            ) from error
        else:
            await self._safe_close(stream)
            return response

    def _build_stream_handler(
        self, protocol_id: TProtocol
    ) -> Callable[[INetStream], Awaitable[None]]:
        async def _stream_handler(stream: INetStream) -> None:
            registration = self._handlers.get(protocol_id)
            if registration is None:
                await self._safe_reset(stream)
                return

            try:
                registration.limiter.acquire_nowait()
            except trio.WouldBlock:
                logger.warning(
                    "request_response inbound limit reached for protocol %s",
                    protocol_id,
                )
                await self._safe_reset(stream)
                return

            try:
                await self._handle_inbound(protocol_id, registration, stream)
            finally:
                registration.limiter.release()

        return _stream_handler

    async def _handle_inbound(
        self,
        protocol_id: TProtocol,
        registration: _HandlerRegistration[object, object],
        stream: INetStream,
    ) -> None:
        context = RequestContext(
            peer_id=stream.muxed_conn.peer_id,
            protocol_id=protocol_id,
        )
        try:
            with trio.fail_after(registration.config.timeout):
                request_payload = await self._read_message(
                    stream, registration.config.max_request_size
                )
                request = self._decode_inbound_request(
                    registration.codec, request_payload
                )
                response = await registration.handler(request, context)
                response_payload = self._encode_inbound_response(
                    registration.codec, response
                )
                self._check_size(
                    response_payload,
                    registration.config.max_response_size,
                    "response payload exceeds configured maximum",
                )
                await self._write_message(
                    stream, response_payload, registration.config.max_response_size
                )
        except trio.TooSlowError:
            logger.warning(
                "request_response handler timed out for protocol %s from peer %s",
                protocol_id,
                context.peer_id,
            )
            await self._safe_reset(stream)
        except RequestResponseError as error:
            logger.warning(
                "request_response handler rejected protocol %s from peer %s: %s",
                protocol_id,
                context.peer_id,
                error,
            )
            await self._safe_reset(stream)
        except (IncompleteReadError, StreamEOF, StreamError, StreamReset) as error:
            logger.warning(
                "request_response stream error for protocol %s from peer %s: %s",
                protocol_id,
                context.peer_id,
                error,
            )
            await self._safe_reset(stream)
        except Exception:
            logger.exception(
                (
                    "request_response unexpected handler failure for protocol %s "
                    "from peer %s"
                ),
                protocol_id,
                context.peer_id,
            )
            await self._safe_reset(stream)
        else:
            await self._safe_close(stream)

    async def _read_message(self, stream: INetStream, max_msg_size: int) -> bytes:
        reader = VarIntLengthMsgReadWriter(stream, max_msg_size=max_msg_size)
        try:
            return await reader.read_msg()
        except MessageTooLarge as error:
            raise MessageTooLargeError(str(error)) from error

    async def _write_message(
        self, stream: INetStream, payload: bytes, max_msg_size: int
    ) -> None:
        writer = VarIntLengthMsgReadWriter(stream, max_msg_size=max_msg_size)
        try:
            await writer.write_msg(payload)
        except MessageTooLarge as error:
            raise MessageTooLargeError(str(error)) from error

    def _check_size(self, payload: bytes, limit: int, message: str) -> None:
        if len(payload) > limit:
            raise MessageTooLargeError(message)

    def _encode_request(
        self, codec: RequestResponseCodec[ReqT, RespT], request: ReqT
    ) -> bytes:
        try:
            payload = codec.encode_request(request)
            return self._ensure_bytes(payload, "request payload must encode to bytes")
        except Exception as error:
            raise RequestEncodeError("failed to encode request payload") from error

    def _decode_response(
        self, codec: RequestResponseCodec[ReqT, RespT], payload: bytes
    ) -> RespT:
        try:
            return codec.decode_response(payload)
        except Exception as error:
            raise ResponseDecodeError("failed to decode response payload") from error

    def _decode_inbound_request(
        self, codec: RequestResponseCodec[object, object], payload: bytes
    ) -> object:
        try:
            return codec.decode_request(payload)
        except Exception as error:
            raise RequestDecodeError("failed to decode request payload") from error

    def _encode_inbound_response(
        self, codec: RequestResponseCodec[object, object], response: object
    ) -> bytes:
        try:
            payload = codec.encode_response(response)
            return self._ensure_bytes(payload, "response payload must encode to bytes")
        except Exception as error:
            raise ResponseEncodeError("failed to encode response payload") from error

    def _ensure_bytes(self, payload: bytes, message: str) -> bytes:
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError(message)
        return bytes(payload)

    def _map_stream_failure(self, error: StreamFailure) -> RequestResponseError:
        cause = error.__cause__
        if isinstance(cause, MultiselectProtocolNotSupportedError):
            return ProtocolNotSupportedError(str(cause))
        if isinstance(
            cause, MultiselectClientError
        ) and "protocol not supported" in str(cause):
            return ProtocolNotSupportedError(str(cause))
        return RequestTransportError(str(error))

    async def _safe_close(self, stream: INetStream | None) -> None:
        if stream is None:
            return
        try:
            await stream.close()
        except Exception:
            logger.debug(
                "failed to close request_response stream cleanly", exc_info=True
            )

    async def _safe_reset(self, stream: INetStream | None) -> None:
        if stream is None:
            return
        try:
            await stream.reset()
        except Exception:
            logger.debug(
                "failed to reset request_response stream cleanly", exc_info=True
            )
