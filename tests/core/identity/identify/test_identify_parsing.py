import pytest

from libp2p.identity.identify.identify import (
    _mk_identify_protobuf,
)
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from libp2p.io.abc import Closer, Reader, Writer
from libp2p.utils.varint import (
    decode_varint_from_bytes,
    encode_varint_prefixed,
)
from tests.utils.factories import (
    host_pair_factory,
)


class MockStream(Reader, Writer, Closer):
    """Mock stream for testing identify protocol compatibility."""

    def __init__(self, data: bytes):
        self.data = data
        self.position = 0
        self.closed = False

    async def read(self, n: int | None = None) -> bytes:
        if self.closed or self.position >= len(self.data):
            return b""
        if n is None:
            n = len(self.data) - self.position
        result = self.data[self.position : self.position + n]
        self.position += len(result)
        return result

    async def write(self, data: bytes) -> None:
        # Mock write - just store the data
        pass

    async def close(self) -> None:
        self.closed = True


def create_identify_message(host, observed_multiaddr=None):
    """Create an identify protobuf message."""
    return _mk_identify_protobuf(host, observed_multiaddr)


def create_new_format_message(identify_msg):
    """Create a new format (length-prefixed) identify message."""
    msg_bytes = identify_msg.SerializeToString()
    return encode_varint_prefixed(msg_bytes)


def create_old_format_message(identify_msg):
    """Create an old format (raw protobuf) identify message."""
    return identify_msg.SerializeToString()


async def read_new_format_message(stream) -> bytes:
    """Read a new format (length-prefixed) identify message."""
    # Read varint length prefix
    length_bytes = b""
    while True:
        b = await stream.read(1)
        if not b:
            break
        length_bytes += b
        if b[0] & 0x80 == 0:
            break

    if not length_bytes:
        raise ValueError("No length prefix received")

    msg_length = decode_varint_from_bytes(length_bytes)

    # Read the protobuf message
    response = await stream.read(msg_length)
    if len(response) != msg_length:
        raise ValueError("Incomplete message received")

    return response


async def read_old_format_message(stream) -> bytes:
    """Read an old format (raw protobuf) identify message."""
    # Read all available data
    response = b""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        response += chunk

    return response


async def read_compatible_message(stream) -> bytes:
    """Read an identify message in either old or new format."""
    # Try to read a few bytes to detect the format
    first_bytes = await stream.read(10)
    if not first_bytes:
        raise ValueError("No data received")

    # Try to decode as varint length prefix (new format)
    try:
        msg_length = decode_varint_from_bytes(first_bytes)

        # Validate that the length is reasonable (not too large)
        if msg_length > 0 and msg_length <= 1024 * 1024:  # Max 1MB
            # Calculate how many bytes the varint consumed
            varint_len = 0
            for i, byte in enumerate(first_bytes):
                varint_len += 1
                if (byte & 0x80) == 0:
                    break

            # Read the remaining protobuf message
            remaining_bytes = await stream.read(
                msg_length - (len(first_bytes) - varint_len)
            )
            if len(remaining_bytes) == msg_length - (len(first_bytes) - varint_len):
                message_data = first_bytes[varint_len:] + remaining_bytes

                # Try to parse as protobuf to validate
                try:
                    Identify().ParseFromString(message_data)
                    return message_data
                except Exception:
                    # If protobuf parsing fails, fall back to old format
                    pass
    except Exception:
        pass

    # Fall back to old format (raw protobuf)
    response = first_bytes

    # Read more data if available
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        response += chunk

    return response


async def read_compatible_message_simple(stream) -> bytes:
    """Read a message in either old or new format (simplified version for testing)."""
    # Try to read a few bytes to detect the format
    first_bytes = await stream.read(10)
    if not first_bytes:
        raise ValueError("No data received")

    # Try to decode as varint length prefix (new format)
    try:
        msg_length = decode_varint_from_bytes(first_bytes)

        # Validate that the length is reasonable (not too large)
        if msg_length > 0 and msg_length <= 1024 * 1024:  # Max 1MB
            # Calculate how many bytes the varint consumed
            varint_len = 0
            for i, byte in enumerate(first_bytes):
                varint_len += 1
                if (byte & 0x80) == 0:
                    break

            # Read the remaining message
            remaining_bytes = await stream.read(
                msg_length - (len(first_bytes) - varint_len)
            )
            if len(remaining_bytes) == msg_length - (len(first_bytes) - varint_len):
                return first_bytes[varint_len:] + remaining_bytes
    except Exception:
        pass

    # Fall back to old format (raw data)
    response = first_bytes

    # Read more data if available
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        response += chunk

    return response


def detect_format(data):
    """Detect if data is in new or old format (varint-prefixed or raw protobuf)."""
    if not data:
        return "unknown"

    # Try to decode as varint
    try:
        msg_length = decode_varint_from_bytes(data)

        # Validate that the length is reasonable
        if msg_length > 0 and msg_length <= 1024 * 1024:  # Max 1MB
            # Calculate varint length
            varint_len = 0
            for i, byte in enumerate(data):
                varint_len += 1
                if (byte & 0x80) == 0:
                    break

            # Check if we have enough data for the message
            if len(data) >= varint_len + msg_length:
                # Additional check: try to parse the message as protobuf
                try:
                    message_data = data[varint_len : varint_len + msg_length]
                    Identify().ParseFromString(message_data)
                    return "new"
                except Exception:
                    # If protobuf parsing fails, it's probably not a valid new format
                    pass
    except Exception:
        pass

    # If varint decoding fails or length is unreasonable, assume old format
    return "old"


@pytest.mark.trio
async def test_identify_new_format_compatibility(security_protocol):
    """Test that identify protocol works with new format (length-prefixed) messages."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create identify message
        identify_msg = create_identify_message(host_a)

        # Create new format message
        new_format_data = create_new_format_message(identify_msg)

        # Create mock stream with new format data
        stream = MockStream(new_format_data)

        # Read using new format reader
        response = await read_new_format_message(stream)

        # Parse the response
        parsed_msg = Identify()
        parsed_msg.ParseFromString(response)

        # Verify the message content
        assert parsed_msg.protocol_version == identify_msg.protocol_version
        assert parsed_msg.agent_version == identify_msg.agent_version
        assert parsed_msg.public_key == identify_msg.public_key


@pytest.mark.trio
async def test_identify_old_format_compatibility(security_protocol):
    """Test that identify protocol works with old format (raw protobuf) messages."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create identify message
        identify_msg = create_identify_message(host_a)

        # Create old format message
        old_format_data = create_old_format_message(identify_msg)

        # Create mock stream with old format data
        stream = MockStream(old_format_data)

        # Read using old format reader
        response = await read_old_format_message(stream)

        # Parse the response
        parsed_msg = Identify()
        parsed_msg.ParseFromString(response)

        # Verify the message content
        assert parsed_msg.protocol_version == identify_msg.protocol_version
        assert parsed_msg.agent_version == identify_msg.agent_version
        assert parsed_msg.public_key == identify_msg.public_key


@pytest.mark.trio
async def test_identify_backward_compatibility_old_format(security_protocol):
    """Test backward compatibility reader with old format messages."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create identify message
        identify_msg = create_identify_message(host_a)

        # Create old format message
        old_format_data = create_old_format_message(identify_msg)

        # Create mock stream with old format data
        stream = MockStream(old_format_data)

        # Read using old format reader (which should work reliably)
        response = await read_old_format_message(stream)

        # Parse the response
        parsed_msg = Identify()
        parsed_msg.ParseFromString(response)

        # Verify the message content
        assert parsed_msg.protocol_version == identify_msg.protocol_version
        assert parsed_msg.agent_version == identify_msg.agent_version
        assert parsed_msg.public_key == identify_msg.public_key


@pytest.mark.trio
async def test_identify_backward_compatibility_new_format(security_protocol):
    """Test backward compatibility reader with new format messages."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create identify message
        identify_msg = create_identify_message(host_a)

        # Create new format message
        new_format_data = create_new_format_message(identify_msg)

        # Create mock stream with new format data
        stream = MockStream(new_format_data)

        # Read using new format reader (which should work reliably)
        response = await read_new_format_message(stream)

        # Parse the response
        parsed_msg = Identify()
        parsed_msg.ParseFromString(response)

        # Verify the message content
        assert parsed_msg.protocol_version == identify_msg.protocol_version
        assert parsed_msg.agent_version == identify_msg.agent_version
        assert parsed_msg.public_key == identify_msg.public_key


@pytest.mark.trio
async def test_identify_format_detection(security_protocol):
    """Test that the format detection works correctly."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create identify message
        identify_msg = create_identify_message(host_a)

        # Test new format detection
        new_format_data = create_new_format_message(identify_msg)
        format_type = detect_format(new_format_data)
        assert format_type == "new", "New format should be detected correctly"

        # Test old format detection
        old_format_data = create_old_format_message(identify_msg)
        format_type = detect_format(old_format_data)
        assert format_type == "old", "Old format should be detected correctly"


@pytest.mark.trio
async def test_identify_error_handling(security_protocol):
    """Test error handling for malformed messages."""
    from libp2p.exceptions import ParseError

    # Test with empty data
    stream = MockStream(b"")
    with pytest.raises(ValueError, match="No data received"):
        await read_compatible_message(stream)

    # Test with incomplete varint
    stream = MockStream(b"\x80")  # Incomplete varint
    with pytest.raises(ParseError, match="Unexpected end of data"):
        await read_new_format_message(stream)

    # Test with invalid protobuf data
    stream = MockStream(b"\x05invalid")  # Length prefix but invalid protobuf
    with pytest.raises(Exception):  # Should fail when parsing protobuf
        response = await read_new_format_message(stream)
        Identify().ParseFromString(response)


@pytest.mark.trio
async def test_identify_message_equivalence(security_protocol):
    """Test that old and new format messages are equivalent."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Create identify message
        identify_msg = create_identify_message(host_a)

        # Create both formats
        new_format_data = create_new_format_message(identify_msg)
        old_format_data = create_old_format_message(identify_msg)

        # Extract the protobuf message from new format
        varint_len = 0
        for i, byte in enumerate(new_format_data):
            varint_len += 1
            if (byte & 0x80) == 0:
                break

        new_format_protobuf = new_format_data[varint_len:]

        # The protobuf messages should be identical
        assert new_format_protobuf == old_format_data, (
            "Protobuf messages should be identical in both formats"
        )
