import pytest
import multiaddr.protocols

# Patch multiaddr to support quic-v1
# This is needed because the installed version of multiaddr might not support
# quic-v1 yet, but we need it for QUIC transport tests.
try:
    multiaddr.protocols.protocol_with_name("quic-v1")
except ValueError:
    try:
        # Map quic-v1 to the existing quic protocol (code 460)
        quic_proto = multiaddr.protocols.protocol_with_name("quic")
        multiaddr.protocols._names_to_protocols["quic-v1"] = quic_proto
    except ValueError:
        pass


@pytest.fixture
def security_protocol():
    return None
