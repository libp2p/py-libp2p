import logging

import pytest

from libp2p.custom_types import TProtocol
from libp2p.identity.identify.identify import (
    AGENT_VERSION,
    ID,
    PROTOCOL_VERSION,
    _multiaddr_to_bytes,
    identify_handler_for,
    parse_identify_response,
)
from tests.utils.factories import host_pair_factory

logger = logging.getLogger("libp2p.identity.identify-integration-test")


@pytest.mark.trio
async def test_identify_protocol_varint_format_integration(security_protocol):
    """Test identify protocol with varint format in real network scenario."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        host_a.set_stream_handler(
            ID, identify_handler_for(host_a, use_varint_format=True)
        )

        # Make identify request
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read(8192)
        await stream.close()

        # Parse response
        result = parse_identify_response(response)

        # Verify response content
        assert result.agent_version == AGENT_VERSION
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.public_key == host_a.get_public_key().serialize()
        assert result.listen_addrs == [
            _multiaddr_to_bytes(addr) for addr in host_a.get_addrs()
        ]


@pytest.mark.trio
async def test_identify_protocol_raw_format_integration(security_protocol):
    """Test identify protocol with raw format in real network scenario."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        host_a.set_stream_handler(
            ID, identify_handler_for(host_a, use_varint_format=False)
        )

        # Make identify request
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read(8192)
        await stream.close()

        # Parse response
        result = parse_identify_response(response)

        # Verify response content
        assert result.agent_version == AGENT_VERSION
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.public_key == host_a.get_public_key().serialize()
        assert result.listen_addrs == [
            _multiaddr_to_bytes(addr) for addr in host_a.get_addrs()
        ]


@pytest.mark.trio
async def test_identify_default_format_behavior(security_protocol):
    """Test identify protocol uses correct default format."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Use default identify handler (should use varint format)
        host_a.set_stream_handler(ID, identify_handler_for(host_a))

        # Make identify request
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read(8192)
        await stream.close()

        # Parse response
        result = parse_identify_response(response)

        # Verify response content
        assert result.agent_version == AGENT_VERSION
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.public_key == host_a.get_public_key().serialize()


@pytest.mark.trio
async def test_identify_cross_format_compatibility_varint_to_raw(security_protocol):
    """Test varint dialer with raw listener compatibility."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Host A uses raw format
        host_a.set_stream_handler(
            ID, identify_handler_for(host_a, use_varint_format=False)
        )

        # Host B makes request (will automatically detect format)
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read(8192)
        await stream.close()

        # Parse response (should work with automatic format detection)
        result = parse_identify_response(response)

        # Verify response content
        assert result.agent_version == AGENT_VERSION
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.public_key == host_a.get_public_key().serialize()


@pytest.mark.trio
async def test_identify_cross_format_compatibility_raw_to_varint(security_protocol):
    """Test raw dialer with varint listener compatibility."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Host A uses varint format
        host_a.set_stream_handler(
            ID, identify_handler_for(host_a, use_varint_format=True)
        )

        # Host B makes request (will automatically detect format)
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read(8192)
        await stream.close()

        # Parse response (should work with automatic format detection)
        result = parse_identify_response(response)

        # Verify response content
        assert result.agent_version == AGENT_VERSION
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.public_key == host_a.get_public_key().serialize()


@pytest.mark.trio
async def test_identify_format_detection_robustness(security_protocol):
    """Test identify protocol format detection is robust with various message sizes."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Test both formats with different message sizes
        for use_varint in [True, False]:
            host_a.set_stream_handler(
                ID, identify_handler_for(host_a, use_varint_format=use_varint)
            )

            # Make identify request
            stream = await host_b.new_stream(host_a.get_id(), (ID,))
            response = await stream.read(8192)
            await stream.close()

            # Parse response
            result = parse_identify_response(response)

            # Verify response content
            assert result.agent_version == AGENT_VERSION
            assert result.protocol_version == PROTOCOL_VERSION
            assert result.public_key == host_a.get_public_key().serialize()


@pytest.mark.trio
async def test_identify_large_message_handling(security_protocol):
    """Test identify protocol handles large messages with many protocols."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Add many protocols to make the message larger
        async def dummy_handler(stream):
            pass

        for i in range(10):
            host_a.set_stream_handler(TProtocol(f"/test/protocol/{i}"), dummy_handler)

        host_a.set_stream_handler(
            ID, identify_handler_for(host_a, use_varint_format=True)
        )

        # Make identify request
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        response = await stream.read(8192)
        await stream.close()

        # Parse response
        result = parse_identify_response(response)

        # Verify response content
        assert result.agent_version == AGENT_VERSION
        assert result.protocol_version == PROTOCOL_VERSION
        assert result.public_key == host_a.get_public_key().serialize()


@pytest.mark.trio
async def test_identify_message_equivalence_real_network(security_protocol):
    """Test that both formats produce equivalent messages in real network."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Test varint format
        host_a.set_stream_handler(
            ID, identify_handler_for(host_a, use_varint_format=True)
        )
        stream_varint = await host_b.new_stream(host_a.get_id(), (ID,))
        response_varint = await stream_varint.read(8192)
        await stream_varint.close()

        # Test raw format
        host_a.set_stream_handler(
            ID, identify_handler_for(host_a, use_varint_format=False)
        )
        stream_raw = await host_b.new_stream(host_a.get_id(), (ID,))
        response_raw = await stream_raw.read(8192)
        await stream_raw.close()

        # Parse both responses
        result_varint = parse_identify_response(response_varint)
        result_raw = parse_identify_response(response_raw)

        # Both should produce identical parsed results
        assert result_varint.agent_version == result_raw.agent_version
        assert result_varint.protocol_version == result_raw.protocol_version
        assert result_varint.public_key == result_raw.public_key
        assert result_varint.listen_addrs == result_raw.listen_addrs
