import hashlib
from types import SimpleNamespace

import pytest

from libp2p.filecoin.constants import (
    FIL_CHAIN_EXCHANGE_PROTOCOL,
    FIL_HELLO_PROTOCOL,
    blocks_topic,
    dht_protocol_name,
    filecoin_message_id,
    messages_topic,
)


def test_protocol_id_constants_match_filecoin_specs() -> None:
    assert str(FIL_HELLO_PROTOCOL) == "/fil/hello/1.0.0"
    assert str(FIL_CHAIN_EXCHANGE_PROTOCOL) == "/fil/chain/xchg/0.0.1"


def test_topic_helpers_match_lotus_format() -> None:
    network_name = "testnetnet"
    assert blocks_topic(network_name) == "/fil/blocks/testnetnet"
    assert messages_topic(network_name) == "/fil/msgs/testnetnet"
    assert str(dht_protocol_name(network_name)) == "/fil/kad/testnetnet"


def test_filecoin_message_id_uses_blake2b_256_on_data() -> None:
    payload = b"hello-filecoin"
    msg = SimpleNamespace(data=payload)
    expected = hashlib.blake2b(payload, digest_size=32).digest()
    assert filecoin_message_id(msg) == expected


def test_filecoin_message_id_requires_bytes_like_data() -> None:
    msg = SimpleNamespace(data="not-bytes")
    with pytest.raises(TypeError):
        filecoin_message_id(msg)


def test_filecoin_message_id_requires_data_attribute() -> None:
    with pytest.raises(AttributeError):
        filecoin_message_id(SimpleNamespace())
