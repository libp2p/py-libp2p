"""Tests for libp2p.filecoin.address – Filecoin address parsing and validation."""

from __future__ import annotations

import pytest

from libp2p.filecoin.address import (
    DELEGATED,
    DEMO_F0_PAYER,
    DEMO_F410_PAYER,
    DEMO_F410_PAYER_TESTNET,
    EAM_NAMESPACE,
    ID,
    address_protocol,
    is_valid_address,
    make_delegated_address,
    make_id_address,
    parse_address,
)


class TestDelegatedAddress:
    def test_roundtrip(self) -> None:
        sub = bytes.fromhex("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
        addr_str = make_delegated_address(EAM_NAMESPACE, sub)
        addr = parse_address(addr_str)

        assert addr.protocol == DELEGATED
        assert addr.is_delegated is True
        assert addr.namespace == EAM_NAMESPACE
        assert addr.subaddress == sub
        assert str(addr) == addr_str
        assert addr.is_testnet is False

    def test_roundtrip_testnet(self) -> None:
        sub = bytes.fromhex("cafebabe" * 5)
        addr_str = make_delegated_address(EAM_NAMESPACE, sub, is_testnet=True)
        addr = parse_address(addr_str)

        assert addr.protocol == DELEGATED
        assert addr.is_testnet is True
        assert addr.namespace == EAM_NAMESPACE
        assert addr.subaddress == sub
        assert str(addr) == addr_str


class TestIdAddress:
    def test_roundtrip(self) -> None:
        addr_str = make_id_address(1001)
        addr = parse_address(addr_str)

        assert addr.protocol == ID
        assert addr.is_delegated is False
        assert addr.is_testnet is False
        assert addr.namespace is None
        assert str(addr) == addr_str

    def test_testnet(self) -> None:
        addr_str = make_id_address(65535, is_testnet=True)
        addr = parse_address(addr_str)
        assert addr.is_testnet is True
        assert addr.protocol == ID
        assert str(addr).startswith("t0")


class TestValidation:
    def test_valid_demo_addresses(self) -> None:
        for name, addr_str in (
            ("DEMO_F410_PAYER", DEMO_F410_PAYER),
            ("DEMO_F0_PAYER", DEMO_F0_PAYER),
            ("DEMO_F410_PAYER_TESTNET", DEMO_F410_PAYER_TESTNET),
        ):
            assert is_valid_address(addr_str), f"{name} should be valid"
            assert str(parse_address(addr_str)) == addr_str

    def test_rejects_empty(self) -> None:
        assert is_valid_address("") is False

    def test_rejects_junk(self) -> None:
        assert is_valid_address("not-an-address") is False

    def test_rejects_missing_prefix(self) -> None:
        assert is_valid_address("x0abc") is False

    def test_rejects_wrong_protocol_byte(self) -> None:
        # f4 prefix with protocol byte 3 in payload
        assert is_valid_address("f4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") is False

    def test_parse_raises_on_invalid(self) -> None:
        with pytest.raises(ValueError):
            parse_address("not-an-address")

    def test_parse_raises_on_empty(self) -> None:
        with pytest.raises(ValueError):
            parse_address("")

    def test_parse_raises_on_wrong_type(self) -> None:
        with pytest.raises(ValueError):
            parse_address(123)  # type: ignore[arg-type]

    def test_parse_handles_whitespace(self) -> None:
        assert is_valid_address(f"  {DEMO_F410_PAYER}  ") is True


class TestAddressProtocol:
    def test_returns_correct_protocol(self) -> None:
        assert address_protocol(DEMO_F410_PAYER) == DELEGATED
        assert address_protocol(DEMO_F0_PAYER) == ID


class TestSubaddress:
    def test_delegated_subaddress(self) -> None:
        addr = parse_address(DEMO_F410_PAYER)
        assert addr.subaddress == bytes.fromhex(
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        )

    def test_non_delegated_raises(self) -> None:
        addr = parse_address(DEMO_F0_PAYER)
        with pytest.raises(ValueError, match="only delegated"):
            addr.subaddress  # noqa: B018


class TestCreateValidatesInputs:
    def test_delegated_negative_namespace(self) -> None:
        with pytest.raises(ValueError, match="namespace"):
            make_delegated_address(-1, b"\x00" * 20)

    def test_delegated_non_bytes_subaddress(self) -> None:
        with pytest.raises(TypeError, match="subaddress"):
            make_delegated_address(10, "not-bytes")  # type: ignore[arg-type]

    def test_id_negative_actor_id(self) -> None:
        with pytest.raises(ValueError, match="actor_id"):
            make_id_address(-1)
