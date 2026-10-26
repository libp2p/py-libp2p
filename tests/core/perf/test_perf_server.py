"""Tests for perf protocol server-side functionality."""

import struct

import pytest

from .conftest import MockNetStream


@pytest.mark.trio
async def test_parse_valid_8_byte_header(perf_service):
    """Verify server correctly parses a valid 8-byte big-endian header."""
    # Create header requesting 1024 bytes back
    recv_bytes = 1024
    header = struct.pack(">Q", recv_bytes)
    # Add some upload data after header
    upload_data = b"x" * 100

    stream = MockNetStream(header + upload_data)
    await perf_service._handle_message(stream)

    # Server should have written exactly 1024 bytes back
    assert len(stream._write_buffer) == recv_bytes
    assert stream._closed is True
    assert stream._reset_called is False


@pytest.mark.trio
async def test_server_extracts_response_length(perf_service):
    """Verify server extracts correct bytes_to_send_back value from header."""
    # Test with specific value: 5000 bytes
    recv_bytes = 5000
    header = struct.pack(">Q", recv_bytes)

    stream = MockNetStream(header)
    await perf_service._handle_message(stream)

    # Server should send exactly 5000 bytes
    assert len(stream._write_buffer) == recv_bytes


@pytest.mark.trio
async def test_server_handles_zero_response_length(perf_service):
    """Edge case: header requests 0 bytes back."""
    recv_bytes = 0
    header = struct.pack(">Q", recv_bytes)
    upload_data = b"y" * 50

    stream = MockNetStream(header + upload_data)
    await perf_service._handle_message(stream)

    # Server should write 0 bytes back
    assert len(stream._write_buffer) == 0
    assert stream._closed is True


@pytest.mark.trio
async def test_server_handles_large_response_length(perf_service):
    """Edge case: header requests large bytes back (1MB)."""
    recv_bytes = 1024 * 1024  # 1MB
    header = struct.pack(">Q", recv_bytes)

    stream = MockNetStream(header)
    await perf_service._handle_message(stream)

    # Server should send exactly 1MB
    assert len(stream._write_buffer) == recv_bytes
    assert stream._closed is True


@pytest.mark.trio
async def test_server_sends_correct_byte_count(perf_service):
    """Verify server sends exactly the requested number of bytes."""
    test_cases = [1, 100, 1024, 65536]

    for recv_bytes in test_cases:
        header = struct.pack(">Q", recv_bytes)
        stream = MockNetStream(header)
        await perf_service._handle_message(stream)

        assert len(stream._write_buffer) == recv_bytes, (
            f"Expected {recv_bytes} bytes, got {len(stream._write_buffer)}"
        )
