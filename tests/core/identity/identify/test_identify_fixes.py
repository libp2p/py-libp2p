import pytest
from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.identity.identify.identify import parse_identify_response
from libp2p.utils import varint


def test_parse_identify_without_agent_version():
    """Bug 5: Identify parser should not require agent_version."""
    identify_msg = Identify()
    identify_msg.public_key = b"fakekey"
    # No agent_version

    # Encode with varint length prefix
    response = identify_msg.SerializeToString()
    length_prefix = varint.encode_uvarint(len(response))
    full_response = length_prefix + response

    parsed = parse_identify_response(full_response)
    assert parsed.public_key == b"fakekey"
