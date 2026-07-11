from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import pytest
import trio

from libp2p.custom_types import TProtocol
from libp2p.request_response import (
    BytesCodec,
    JSONCodec,
    MessageTooLargeError,
    ProtocolNotSupportedError,
    RequestContext,
    RequestResponse,
    RequestResponseConfig,
    RequestTimeoutError,
    RequestTransportError,
    ResponseDecodeError,
)
from libp2p.tools.utils import connect
from libp2p.utils import encode_varint_prefixed
from tests.utils.factories import HostFactory

PROTO_V1 = TProtocol("/example/request-response/1.0.0")
PROTO_V2 = TProtocol("/example/request-response/2.0.0")


class DummyNetStream:
    def __init__(
        self,
        initial_bytes: bytes = b"",
        *,
        peer_id: str = "peer-1",
        read_delay: float = 0.0,
    ) -> None:
        self._buffer = bytearray(initial_bytes)
        self._read_delay = read_delay
        self.written = bytearray()
        self.closed = False
        self.reset_called = False
        self.muxed_conn = SimpleNamespace(peer_id=peer_id)

    async def read(self, n: int | None = None) -> bytes:
        if self._read_delay:
            await trio.sleep(self._read_delay)
        if n is None:
            n = len(self._buffer)
        chunk = bytes(self._buffer[:n])
        del self._buffer[:n]
        return chunk

    async def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def close(self) -> None:
        self.closed = True

    async def reset(self) -> None:
        self.reset_called = True


StreamHandler = Callable[[DummyNetStream], Awaitable[None]]


class DummyHost:
    def __init__(self, stream: DummyNetStream | Exception | None = None) -> None:
        self.stream = stream
        self.handlers: dict[TProtocol, StreamHandler] = {}
        self.new_stream_calls: list[tuple[object, tuple[TProtocol, ...]]] = []

    async def new_stream(
        self, peer_id: object, protocol_ids: list[TProtocol] | tuple[TProtocol, ...]
    ):
        self.new_stream_calls.append((peer_id, tuple(protocol_ids)))
        if isinstance(self.stream, Exception):
            raise self.stream
        if self.stream is None:
            raise RuntimeError("stream not configured")
        return self.stream

    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandler
    ) -> None:
        self.handlers[protocol_id] = stream_handler

    def remove_stream_handler(self, protocol_id: TProtocol) -> None:
        self.handlers.pop(protocol_id, None)


@pytest.mark.trio
async def test_send_request_rejects_oversized_request_before_opening_stream() -> None:
    host = DummyHost(DummyNetStream())
    rr = RequestResponse(host)  # type: ignore[arg-type]

    with pytest.raises(MessageTooLargeError):
        await rr.send_request(
            peer_id="peer",  # type: ignore[arg-type]
            protocol_ids=[PROTO_V1],
            request=b"12345",
            codec=BytesCodec(),
            config=RequestResponseConfig(max_request_size=4),
        )

    assert host.new_stream_calls == []


@pytest.mark.trio
async def test_send_request_raises_decode_error_for_malformed_response() -> None:
    stream = DummyNetStream(encode_varint_prefixed(b"not-json"))
    host = DummyHost(stream)
    rr = RequestResponse(host)  # type: ignore[arg-type]

    with pytest.raises(ResponseDecodeError):
        await rr.send_request(
            peer_id="peer",  # type: ignore[arg-type]
            protocol_ids=[PROTO_V1],
            request={"msg": "hello"},
            codec=JSONCodec(),
        )

    assert stream.reset_called is True


@pytest.mark.trio
async def test_inbound_malformed_request_resets_stream_and_skips_handler() -> None:
    stream = DummyNetStream(encode_varint_prefixed(b"not-json"))
    host = DummyHost()
    rr = RequestResponse(host)  # type: ignore[arg-type]
    handler_called = False

    async def handler(request: dict[str, str], context: object) -> dict[str, str]:
        nonlocal handler_called
        handler_called = True
        return request

    rr.set_handler(PROTO_V1, handler=handler, codec=JSONCodec())

    stream_handler = host.handlers[PROTO_V1]
    await stream_handler(stream)

    assert handler_called is False
    assert stream.reset_called is True
    assert stream.closed is False


@pytest.mark.trio
async def test_inbound_oversized_response_resets_before_write() -> None:
    stream = DummyNetStream(encode_varint_prefixed(b"ping"))
    host = DummyHost()
    rr = RequestResponse(host)  # type: ignore[arg-type]

    async def handler(request: bytes, context: object) -> bytes:
        return b"toolong"

    rr.set_handler(
        PROTO_V1,
        handler=handler,
        codec=BytesCodec(),
        config=RequestResponseConfig(max_response_size=4),
    )

    stream_handler = host.handlers[PROTO_V1]
    await stream_handler(stream)

    assert bytes(stream.written) == b""
    assert stream.reset_called is True


@pytest.mark.trio
async def test_inbound_handler_exception_resets_stream() -> None:
    stream = DummyNetStream(encode_varint_prefixed(b"ping"))
    host = DummyHost()
    rr = RequestResponse(host)  # type: ignore[arg-type]

    async def handler(request: bytes, context: object) -> bytes:
        raise RuntimeError("boom")

    rr.set_handler(PROTO_V1, handler=handler, codec=BytesCodec())

    stream_handler = host.handlers[PROTO_V1]
    await stream_handler(stream)

    assert stream.reset_called is True


@pytest.mark.trio
async def test_send_request_timeout_resets_stream() -> None:
    stream = DummyNetStream(read_delay=0.2)
    host = DummyHost(stream)
    rr = RequestResponse(host)  # type: ignore[arg-type]

    with pytest.raises(RequestTimeoutError):
        await rr.send_request(
            peer_id="peer",  # type: ignore[arg-type]
            protocol_ids=[PROTO_V1],
            request=b"ping",
            codec=BytesCodec(),
            config=RequestResponseConfig(timeout=0.05),
        )

    assert stream.reset_called is True


@pytest.mark.trio
async def test_send_request_clean_close_before_response_raises_transport_error() -> (
    None
):
    stream = DummyNetStream()
    host = DummyHost(stream)
    rr = RequestResponse(host)  # type: ignore[arg-type]

    with pytest.raises(RequestTransportError):
        await rr.send_request(
            peer_id="peer",  # type: ignore[arg-type]
            protocol_ids=[PROTO_V1],
            request=b"ping",
            codec=BytesCodec(),
        )

    assert stream.reset_called is True


def test_remove_handler_unregisters_protocol() -> None:
    host = DummyHost()
    rr = RequestResponse(host)  # type: ignore[arg-type]

    async def handler(request: bytes, context: object) -> bytes:
        return request

    rr.set_handler(PROTO_V1, handler=handler, codec=BytesCodec())
    assert PROTO_V1 in host.handlers

    rr.remove_handler(PROTO_V1)
    assert PROTO_V1 not in host.handlers


@pytest.mark.trio
async def test_inbound_concurrency_limit_resets_extra_streams() -> None:
    host = DummyHost()
    rr = RequestResponse(host)  # type: ignore[arg-type]
    release = trio.Event()
    started = trio.Event()

    async def slow_handler(request: bytes, context: object) -> bytes:
        started.set()
        await release.wait()
        return request

    rr.set_handler(
        PROTO_V1,
        handler=slow_handler,
        codec=BytesCodec(),
        config=RequestResponseConfig(max_concurrent_inbound=1),
    )

    stream_handler = host.handlers[PROTO_V1]
    stream_one = DummyNetStream(encode_varint_prefixed(b"first"))
    stream_two = DummyNetStream(encode_varint_prefixed(b"second"))

    async with trio.open_nursery() as nursery:
        nursery.start_soon(stream_handler, stream_one)
        await started.wait()
        nursery.start_soon(stream_handler, stream_two)
        await trio.sleep(0.05)
        assert stream_two.reset_called is True
        release.set()


@pytest.mark.trio
async def test_request_response_round_trip_integration(security_protocol) -> None:
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        rr_client = RequestResponse(hosts[0])
        rr_server = RequestResponse(hosts[1])

        async def handler(
            request: dict[str, str], context: RequestContext
        ) -> dict[str, str]:
            return {"echo": request["msg"], "peer": str(context.peer_id)}

        rr_server.set_handler(PROTO_V1, handler=handler, codec=JSONCodec())
        await connect(hosts[0], hosts[1])

        response = await rr_client.send_request(
            peer_id=hosts[1].get_id(),
            protocol_ids=[PROTO_V1],
            request={"msg": "hello"},
            codec=JSONCodec(),
        )

        assert response["echo"] == "hello"


@pytest.mark.trio
async def test_request_response_protocol_preference_integration(
    security_protocol,
) -> None:
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        rr_client = RequestResponse(hosts[0])
        rr_server = RequestResponse(hosts[1])

        async def handler(request: bytes, context: object) -> bytes:
            return b"pong"

        rr_server.set_handler(PROTO_V1, handler=handler, codec=BytesCodec())
        await connect(hosts[0], hosts[1])

        response = await rr_client.send_request(
            peer_id=hosts[1].get_id(),
            protocol_ids=[PROTO_V2, PROTO_V1],
            request=b"ping",
            codec=BytesCodec(),
        )

        assert response == b"pong"


@pytest.mark.trio
async def test_request_response_removed_handler_integration(security_protocol) -> None:
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol
    ) as hosts:
        rr_client = RequestResponse(hosts[0])
        rr_server = RequestResponse(hosts[1])

        async def handler(request: bytes, context):
            return request

        rr_server.set_handler(PROTO_V1, handler=handler, codec=BytesCodec())
        rr_server.remove_handler(PROTO_V1)
        await connect(hosts[0], hosts[1])

        with pytest.raises(ProtocolNotSupportedError):
            await rr_client.send_request(
                peer_id=hosts[1].get_id(),
                protocol_ids=[PROTO_V1],
                request=b"ping",
                codec=BytesCodec(),
            )
