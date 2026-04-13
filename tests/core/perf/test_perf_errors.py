"""Tests for perf protocol error handling paths."""

import struct

import pytest

from libp2p.custom_types import TProtocol
from libp2p.perf import PerfService
from tests.utils.factories import host_pair_factory

from .conftest import MockNetStream

# =============================================================================
# Server Error Path Tests
# =============================================================================


@pytest.mark.trio
async def test_server_stream_reset_before_header(perf_service):
    """Server handles stream reset/close before receiving any header bytes."""
    # Stream closes immediately with no data
    stream = MockNetStream(b"", close_after_bytes=0)
    await perf_service._handle_message(stream)

    # Server should reset the stream on error
    assert stream._reset_called is True


@pytest.mark.trio
async def test_server_incomplete_header(perf_service):
    """Server handles incomplete header (< 8 bytes received before stream closes)."""
    # Only 4 bytes of header, then stream closes
    incomplete_header = b"\x00\x00\x00\x01"  # Only 4 bytes
    stream = MockNetStream(incomplete_header)
    await perf_service._handle_message(stream)

    # Server should reset the stream when header is incomplete
    assert stream._reset_called is True


@pytest.mark.trio
async def test_server_error_during_read(perf_service):
    """Server properly resets stream on read errors."""
    # Stream will raise an error on first read
    stream = MockNetStream(b"", raise_on_read=True)
    await perf_service._handle_message(stream)

    # Server should reset the stream on read error
    assert stream._reset_called is True


@pytest.mark.trio
async def test_server_read_error_after_partial_header(perf_service):
    """Server resets stream when read error occurs after partial header."""
    # Provide 4 bytes, then error on next read
    partial_header = b"\x00\x00\x00\x01"
    stream = MockNetStream(partial_header, raise_after_bytes=4)
    await perf_service._handle_message(stream)

    # Server should reset the stream
    assert stream._reset_called is True


@pytest.mark.trio
async def test_server_resets_stream_when_service_stopped(perf_service):
    """Stopped service should reject inbound perf streams."""
    await perf_service.stop()
    stream = MockNetStream(struct.pack(">Q", 64) + b"x" * 32)
    await perf_service._handle_message(stream)

    assert stream._reset_called is True
    assert stream._write_buffer == b""


# =============================================================================
# Client Error Path Tests
# =============================================================================


@pytest.mark.trio
async def test_client_stream_reset_mid_upload(security_protocol):
    """Client handles stream reset during upload phase."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Server that resets stream after reading some bytes
        async def resetting_server_handler(stream):
            # Read a bit then reset
            await stream.read(100)
            await stream.reset()

        host_a.set_stream_handler(TProtocol("/perf/1.0.0"), resetting_server_handler)

        client = PerfService(host_b)

        recv_bytes = 1000
        send_bytes = 10000  # Large upload to ensure we hit the reset

        # Should raise an exception due to stream reset
        with pytest.raises(Exception):
            async for _ in client.measure_performance(
                host_a.get_addrs()[0].encapsulate(f"/p2p/{host_a.get_id()}"),
                send_bytes,
                recv_bytes,
            ):
                pass


@pytest.mark.trio
async def test_client_byte_count_mismatch(security_protocol):
    """Client raises ValueError when server sends fewer bytes than requested."""
    from libp2p.network.stream.exceptions import StreamEOF

    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Server that sends fewer bytes than the client expects
        async def short_response_handler(stream):
            # Read the 8-byte header to get requested bytes
            header = await stream.read(8)
            requested_bytes = struct.unpack(">Q", header)[0]

            # Drain the upload data (handle EOF when client finishes sending)
            try:
                while True:
                    data = await stream.read(4096)
                    if not data:
                        break
            except StreamEOF:
                pass  # Expected when client closes write side

            # Intentionally send fewer bytes than requested
            bytes_to_send = max(0, requested_bytes - 100)
            await stream.write(b"\x00" * bytes_to_send)
            await stream.close()

        host_a.set_stream_handler(TProtocol("/perf/1.0.0"), short_response_handler)

        client = PerfService(host_b)

        recv_bytes = 1000  # Request 1000 bytes
        send_bytes = 100

        # Should raise ValueError due to byte count mismatch
        with pytest.raises(ValueError) as exc_info:
            async for _ in client.measure_performance(
                host_a.get_addrs()[0].encapsulate(f"/p2p/{host_a.get_id()}"),
                send_bytes,
                recv_bytes,
            ):
                pass

        # Verify the error message contains expected information
        error_msg = str(exc_info.value)
        assert "Expected to receive" in error_msg or "expected" in error_msg.lower()
