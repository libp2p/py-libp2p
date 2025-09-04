import pytest

from libp2p.custom_types import (
    TMuxerOptions,
    TSecurityOptions,
)
from libp2p.transport.upgrader import (
    TransportUpgrader,
)


@pytest.mark.trio
async def test_transport_upgrader_security_and_muxer_initialization():
    """Test TransportUpgrader initializes security and muxer multistreams correctly."""
    secure_transports: TSecurityOptions = {}
    muxer_transports: TMuxerOptions = {}
    negotiate_timeout = 15

    upgrader = TransportUpgrader(
        secure_transports, muxer_transports, negotiate_timeout=negotiate_timeout
    )

    # Verify security multistream initialization
    assert upgrader.security_multistream.transports == secure_transports
    # Verify muxer multistream initialization and timeout
    assert upgrader.muxer_multistream.transports == muxer_transports
    assert upgrader.muxer_multistream.negotiate_timeout == negotiate_timeout
