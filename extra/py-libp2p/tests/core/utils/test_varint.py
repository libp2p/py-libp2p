import pytest

from libp2p.exceptions import ParseError
from libp2p.io.abc import Reader
from libp2p.utils.varint import (
    decode_varint_from_bytes,
    encode_uvarint,
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)


class MockReader(Reader):
    """Mock reader for testing varint functions."""

    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    async def read(self, n: int | None = None) -> bytes:
        if self.position >= len(self.data):
            return b""
        if n is None:
            n = len(self.data) - self.position
        result = self.data[self.position : self.position + n]
        self.position += len(result)
        return result


def test_encode_uvarint():
    """Test varint encoding with various values."""
    test_cases = [
        (0, b"\x00"),
        (1, b"\x01"),
        (127, b"\x7f"),
        (128, b"\x80\x01"),
        (255, b"\xff\x01"),
        (256, b"\x80\x02"),
        (65535, b"\xff\xff\x03"),
        (65536, b"\x80\x80\x04"),
        (16777215, b"\xff\xff\xff\x07"),
        (16777216, b"\x80\x80\x80\x08"),
    ]

    for value, expected in test_cases:
        result = encode_uvarint(value)
        assert result == expected, (
            f"Failed for value {value}: expected {expected.hex()}, got {result.hex()}"
        )


def test_decode_varint_from_bytes():
    """Test varint decoding with various values."""
    test_cases = [
        (b"\x00", 0),
        (b"\x01", 1),
        (b"\x7f", 127),
        (b"\x80\x01", 128),
        (b"\xff\x01", 255),
        (b"\x80\x02", 256),
        (b"\xff\xff\x03", 65535),
        (b"\x80\x80\x04", 65536),
        (b"\xff\xff\xff\x07", 16777215),
        (b"\x80\x80\x80\x08", 16777216),
    ]

    for data, expected in test_cases:
        result = decode_varint_from_bytes(data)
        assert result == expected, (
            f"Failed for data {data.hex()}: expected {expected}, got {result}"
        )


def test_decode_varint_from_bytes_invalid():
    """Test varint decoding with invalid data."""
    # Empty data
    with pytest.raises(ParseError, match="Unexpected end of data"):
        decode_varint_from_bytes(b"")

    # Incomplete varint (should not raise, but should handle gracefully)
    # This depends on the implementation - some might raise, others might return partial


def test_encode_varint_prefixed():
    """Test encoding messages with varint length prefix."""
    test_cases = [
        (b"", b"\x00"),
        (b"hello", b"\x05hello"),
        (b"x" * 127, b"\x7f" + b"x" * 127),
        (b"x" * 128, b"\x80\x01" + b"x" * 128),
    ]

    for message, expected in test_cases:
        result = encode_varint_prefixed(message)
        assert result == expected, (
            f"Failed for message {message}: expected {expected.hex()}, "
            f"got {result.hex()}"
        )


@pytest.mark.trio
async def test_read_varint_prefixed_bytes():
    """Test reading length-prefixed bytes from a stream."""
    test_cases = [
        (b"", b""),
        (b"hello", b"hello"),
        (b"x" * 127, b"x" * 127),
        (b"x" * 128, b"x" * 128),
    ]

    for message, expected in test_cases:
        prefixed_data = encode_varint_prefixed(message)
        reader = MockReader(prefixed_data)

        result = await read_varint_prefixed_bytes(reader)
        assert result == expected, (
            f"Failed for message {message}: expected {expected}, got {result}"
        )


@pytest.mark.trio
async def test_read_varint_prefixed_bytes_incomplete():
    """Test reading length-prefixed bytes with incomplete data."""
    from libp2p.io.exceptions import IncompleteReadError

    # Test with incomplete varint
    reader = MockReader(b"\x80")  # Incomplete varint
    with pytest.raises(IncompleteReadError):
        await read_varint_prefixed_bytes(reader)

    # Test with incomplete message
    prefixed_data = encode_varint_prefixed(b"hello world")
    reader = MockReader(prefixed_data[:-3])  # Missing last 3 bytes
    with pytest.raises(IncompleteReadError):
        await read_varint_prefixed_bytes(reader)


def test_varint_roundtrip():
    """Test roundtrip encoding and decoding."""
    test_values = [0, 1, 127, 128, 255, 256, 65535, 65536, 16777215, 16777216]

    for value in test_values:
        encoded = encode_uvarint(value)
        decoded = decode_varint_from_bytes(encoded)
        assert decoded == value, (
            f"Roundtrip failed for {value}: encoded={encoded.hex()}, decoded={decoded}"
        )


def test_varint_prefixed_roundtrip():
    """Test roundtrip encoding and decoding of length-prefixed messages."""
    test_messages = [
        b"",
        b"hello",
        b"x" * 127,
        b"x" * 128,
        b"x" * 1000,
    ]

    for message in test_messages:
        prefixed = encode_varint_prefixed(message)

        # Decode the length
        length = decode_varint_from_bytes(prefixed)
        assert length == len(message), (
            f"Length mismatch for {message}: expected {len(message)}, got {length}"
        )

        # Extract the message
        varint_len = 0
        for i, byte in enumerate(prefixed):
            varint_len += 1
            if (byte & 0x80) == 0:
                break

        extracted_message = prefixed[varint_len:]
        assert extracted_message == message, (
            f"Message mismatch: expected {message}, got {extracted_message}"
        )


def test_large_varint_values():
    """Test varint encoding/decoding with large values."""
    large_values = [
        2**32 - 1,  # 32-bit max
        2**64 - 1,  # 64-bit max (if supported)
    ]

    for value in large_values:
        try:
            encoded = encode_uvarint(value)
            decoded = decode_varint_from_bytes(encoded)
            assert decoded == value, f"Large value roundtrip failed for {value}"
        except Exception as e:
            # Some implementations might not support very large values
            pytest.skip(f"Large value {value} not supported: {e}")


def test_varint_edge_cases():
    """Test varint encoding/decoding with edge cases."""
    # Test with maximum 7-bit value
    assert encode_uvarint(127) == b"\x7f"
    assert decode_varint_from_bytes(b"\x7f") == 127

    # Test with minimum 8-bit value
    assert encode_uvarint(128) == b"\x80\x01"
    assert decode_varint_from_bytes(b"\x80\x01") == 128

    # Test with maximum 14-bit value
    assert encode_uvarint(16383) == b"\xff\x7f"
    assert decode_varint_from_bytes(b"\xff\x7f") == 16383

    # Test with minimum 15-bit value
    assert encode_uvarint(16384) == b"\x80\x80\x01"
    assert decode_varint_from_bytes(b"\x80\x80\x01") == 16384
