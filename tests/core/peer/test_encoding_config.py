"""Tests for encoding_config module and encoding preference integration."""

import hashlib

import pytest
import base58 as b58
import multibase

from libp2p.encoding_config import (
    encoding_override,
    get_default_encoding,
    list_supported_encodings,
    set_default_encoding,
)
from libp2p.kad_dht.utils import bytes_to_base58, bytes_to_multibase
from libp2p.peer.id import ID
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import get_content_addressed_msg_id


class TestEncodingConfig:
    """Tests for the encoding_config module itself."""

    def setup_method(self) -> None:
        """Reset to base58btc before every test."""
        set_default_encoding("base58btc")

    def teardown_method(self) -> None:
        """Reset after every test so we don't leak state."""
        set_default_encoding("base58btc")

    def test_default_encoding_is_base58btc(self) -> None:
        assert get_default_encoding() == "base58btc"

    def test_set_default_encoding(self) -> None:
        set_default_encoding("base32")
        assert get_default_encoding() == "base32"

    def test_set_unsupported_encoding_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported encoding"):
            set_default_encoding("base999_invalid")

    def test_encoding_override_context_manager(self) -> None:
        assert get_default_encoding() == "base58btc"
        with encoding_override("base64"):
            assert get_default_encoding() == "base64"
        assert get_default_encoding() == "base58btc"

    def test_encoding_override_restores_on_exception(self) -> None:
        assert get_default_encoding() == "base58btc"
        with pytest.raises(RuntimeError):
            with encoding_override("base32"):
                assert get_default_encoding() == "base32"
                raise RuntimeError("boom")
        assert get_default_encoding() == "base58btc"

    def test_encoding_override_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            with encoding_override("not_real"):
                pass
        assert get_default_encoding() == "base58btc"

    def test_list_supported_encodings(self) -> None:
        supported = list_supported_encodings()
        assert isinstance(supported, list)
        assert "base58btc" in supported
        assert "base32" in supported
        assert "base64" in supported
        assert supported == sorted(supported)


class TestIDWithConfig:
    """Tests that ID.to_multibase respects the global config."""

    def setup_method(self) -> None:
        set_default_encoding("base58btc")

    def teardown_method(self) -> None:
        set_default_encoding("base58btc")

    def test_to_multibase_uses_default(self) -> None:
        pid = ID(b"\x12\x34\x56")
        assert pid.to_multibase().startswith("z")

    def test_to_multibase_follows_config_change(self) -> None:
        pid = ID(b"\x12\x34\x56")
        set_default_encoding("base32")
        encoded = pid.to_multibase()
        assert encoded.startswith("b")

    def test_to_multibase_explicit_overrides_config(self) -> None:
        pid = ID(b"\x12\x34\x56")
        set_default_encoding("base32")
        encoded = pid.to_multibase("base64")
        assert encoded.startswith("m")

    def test_to_multibase_with_encoding_override(self) -> None:
        pid = ID(b"\x12\x34\x56")
        with encoding_override("base64url"):
            encoded = pid.to_multibase()
            assert encoded.startswith("u")
        assert pid.to_multibase().startswith("z")

    def test_roundtrip_with_different_defaults(self) -> None:
        pid = ID(b"\xaa\xbb\xcc\xdd")
        for enc in ("base58btc", "base32", "base64", "base64url"):
            set_default_encoding(enc)
            encoded = pid.to_multibase()
            decoded = ID.from_multibase(encoded)
            assert decoded == pid, f"round-trip failed for {enc}"


class TestDHTUtilsWithConfig:
    """Tests that DHT bytes_to_multibase respects the global config."""

    def setup_method(self) -> None:
        set_default_encoding("base58btc")

    def teardown_method(self) -> None:
        set_default_encoding("base58btc")

    def test_bytes_to_multibase_uses_default(self) -> None:
        data = b"hello"
        encoded = bytes_to_multibase(data)
        assert encoded.startswith("z")

    def test_bytes_to_multibase_follows_config_change(self) -> None:
        data = b"hello"
        set_default_encoding("base32")
        encoded = bytes_to_multibase(data)
        assert encoded.startswith("b")

    def test_bytes_to_multibase_explicit_overrides_config(self) -> None:
        data = b"hello"
        set_default_encoding("base32")
        encoded = bytes_to_multibase(data, "base64")
        assert encoded.startswith("m")

    def test_bytes_to_base58_no_prefix(self) -> None:
        """bytes_to_base58 must return plain base58 without a multibase prefix."""
        data = b"hello"
        result = bytes_to_base58(data)
        expected = b58.b58encode(data).decode()
        assert result == expected
        assert not result.startswith("z") or expected.startswith("z")


class TestContentAddressedMsgId:
    """Tests for get_content_addressed_msg_id multibase encoding."""

    def setup_method(self) -> None:
        set_default_encoding("base58btc")

    def teardown_method(self) -> None:
        set_default_encoding("base58btc")

    def test_returns_multibase_encoded_hash(self) -> None:
        msg = rpc_pb2.Message(data=b"hello world")
        result = get_content_addressed_msg_id(msg)
        expected_digest = hashlib.sha256(b"hello world").digest()
        expected = multibase.encode("base58btc", expected_digest)
        assert result == expected

    def test_uses_default_encoding(self) -> None:
        msg = rpc_pb2.Message(data=b"test data")
        result = get_content_addressed_msg_id(msg)
        assert bytes(result).decode().startswith("z")

    def test_follows_config_change(self) -> None:
        msg = rpc_pb2.Message(data=b"test data")
        set_default_encoding("base32")
        result = get_content_addressed_msg_id(msg)
        assert bytes(result).decode().startswith("b")

    def test_explicit_encoding_overrides_config(self) -> None:
        msg = rpc_pb2.Message(data=b"test data")
        set_default_encoding("base32")
        result = get_content_addressed_msg_id(msg, encoding="base64")
        assert bytes(result).decode().startswith("m")

    def test_different_data_produces_different_ids(self) -> None:
        msg1 = rpc_pb2.Message(data=b"message one")
        msg2 = rpc_pb2.Message(data=b"message two")
        assert get_content_addressed_msg_id(msg1) != get_content_addressed_msg_id(msg2)

    def test_same_data_produces_same_id(self) -> None:
        msg1 = rpc_pb2.Message(data=b"same content")
        msg2 = rpc_pb2.Message(data=b"same content")
        assert get_content_addressed_msg_id(msg1) == get_content_addressed_msg_id(msg2)
