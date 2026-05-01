"""
Filecoin address types and validation (f1, f3, f4/f410, testnet prefixes).

Spec: https://spec.filecoin.io/appendix/address/

Address layout::

    |----------|------|------------------------- ... -------|
      protocol   payload (1+ bytes, protocol-dependent)
                  |
                  For f4 (DELEGATED): namespace (uvarint) + sub-address
                  For f410: namespace=10 (Eth Address Manager)

    Final encoding: base32 (RFC 4648, lowercase, no padding) with a
    4-byte blake2b-160 checksum appended before encoding.

"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Final, Literal

import varint

# Protocol indicator byte values
# https://spec.filecoin.io/appendix/address/#protocol-indicator
ID: Final[Literal[0]] = 0
SECP256K1: Final[Literal[1]] = 1
ACTOR: Final[Literal[2]] = 2
BLS: Final[Literal[3]] = 3
DELEGATED: Final[Literal[4]] = 4

Protocol = Literal[0, 1, 2, 3, 4]

# f410 / Eth Address Manager namespace
EAM_NAMESPACE: Final = 10

_BASE32_ALPHABET: Final = "abcdefghijklmnopqrstuvwxyz234567"
_BASE32_DECODE_TABLE: Final = {
    char: index for index, char in enumerate(_BASE32_ALPHABET)
}

_MAINNET_PREFIXES: Final = {
    ID: "f0",
    SECP256K1: "f1",
    ACTOR: "f2",
    BLS: "f3",
    DELEGATED: "f4",
}
_TESTNET_PREFIXES: Final = {
    ID: "t0",
    SECP256K1: "t1",
    ACTOR: "t2",
    BLS: "t3",
    DELEGATED: "t4",
}


@dataclass(frozen=True, slots=True)
class FilecoinAddress:
    """A parsed Filecoin address."""

    protocol: Protocol
    is_testnet: bool
    payload: bytes
    namespace: int | None

    def __str__(self) -> str:
        return _encode(self.protocol, self.is_testnet, self.payload)

    @property
    def is_delegated(self) -> bool:
        return self.protocol == DELEGATED

    @property
    def subaddress(self) -> bytes:
        """For delegated addresses, the subaddress bytes (after namespace prefix)."""
        if self.protocol != DELEGATED:
            raise ValueError("only delegated addresses have a subaddress")
        if self.namespace is None:
            raise ValueError("delegated address is missing namespace")
        consumed = len(varint.encode(self.namespace))
        return self.payload[consumed:]

    @property
    def prefix(self) -> str:
        return _prefix_for(self.protocol, self.is_testnet)


def parse_address(addr_str: str) -> FilecoinAddress:
    """
    Parse a Filecoin address string (e.g. ``f1...``, ``f410...``, ``t410...``).

    Raises :exc:`ValueError` if *addr_str* is not a valid Filecoin address.
    """
    if not isinstance(addr_str, str):
        raise ValueError(f"address must be a string, got {type(addr_str).__name__}")

    addr_str = addr_str.strip()
    if not addr_str:
        raise ValueError("address must not be empty")

    protocol, is_testnet = _parse_prefix(addr_str)
    prefix = _prefix_for(protocol, is_testnet)

    b32_part = addr_str[len(prefix) :]
    if not b32_part:
        raise ValueError(f"address has no payload after prefix '{prefix}'")

    raw = _base32_decode(b32_part)
    if len(raw) < 5:
        raise ValueError(
            f"decoded address too short: {len(raw)} bytes "
            f"(need at least 5 for protocol + checksum)"
        )

    actual_protocol = raw[0]
    if actual_protocol != protocol:
        raise ValueError(
            f"protocol mismatch: prefix indicates {protocol} "
            f"but payload byte is {actual_protocol}"
        )

    payload = raw[1:-4]
    checksum = raw[-4:]
    expected_checksum = _compute_checksum(raw[0], payload)
    if checksum != expected_checksum:
        raise ValueError(
            f"checksum mismatch: got {checksum.hex()}, "
            f"expected {expected_checksum.hex()}"
        )

    namespace: int | None = None
    if protocol == DELEGATED:
        if not payload:
            raise ValueError("delegated address has no namespace in payload")
        namespace = varint.decode_bytes(payload)

    return FilecoinAddress(
        protocol=protocol,
        is_testnet=is_testnet,
        payload=raw[1:-4],
        namespace=namespace,
    )


def is_valid_address(addr_str: str) -> bool:
    """Return ``True`` if *addr_str* is a syntactically valid Filecoin address."""
    try:
        parse_address(addr_str)
    except (ValueError, TypeError):
        return False
    return True


def make_delegated_address(
    namespace: int,
    subaddress: bytes,
    *,
    is_testnet: bool = False,
) -> str:
    """
    Create a delegated (f4/t4) Filecoin address.

    *namespace* is the integer namespace (e.g. 10 for Ethereum Address Manager).
    *subaddress* is the raw sub-address bytes (e.g. 20-byte Ethereum address).
    """
    if namespace < 0:
        raise ValueError(f"namespace must be non-negative, got {namespace}")
    if not isinstance(subaddress, (bytes, bytearray)):
        raise TypeError(f"subaddress must be bytes, got {type(subaddress).__name__}")

    ns_bytes = varint.encode(namespace)
    payload = ns_bytes + bytes(subaddress)
    return _encode(DELEGATED, is_testnet, payload)


def make_id_address(actor_id: int, *, is_testnet: bool = False) -> str:
    """Create an ID address (f0/t0) from a numeric actor ID."""
    if actor_id < 0:
        raise ValueError(f"actor_id must be non-negative, got {actor_id}")
    payload = varint.encode(actor_id)
    return _encode(ID, is_testnet, payload)


def address_protocol(addr_str: str) -> Protocol:
    """Return the protocol indicator byte from *addr_str* without full parsing."""
    return parse_address(addr_str).protocol


# ---- internal helpers ----


def _prefix_for(protocol: Protocol, is_testnet: bool) -> str:
    prefixes = _TESTNET_PREFIXES if is_testnet else _MAINNET_PREFIXES
    return prefixes[protocol]


def _parse_prefix(addr_str: str) -> tuple[Protocol, bool]:
    if addr_str.startswith("t"):
        prefixes = _TESTNET_PREFIXES
        is_testnet = True
    elif addr_str.startswith("f"):
        prefixes = _MAINNET_PREFIXES
        is_testnet = False
    else:
        raise ValueError(
            "address must start with 'f' (mainnet) or 't' (testnet), "
            f"got {addr_str[:1]!r}"
        )

    found: tuple[Protocol, bool] | None = None
    for protocol, prefix in prefixes.items():
        if addr_str.startswith(prefix):
            found = (protocol, is_testnet)
            break

    if found is None:
        raise ValueError(f"unrecognised address prefix in {addr_str!r}")
    return found


def _compute_checksum(protocol_byte: int, payload: bytes) -> bytes:
    hasher = hashlib.blake2b(digest_size=20)
    hasher.update(bytes([protocol_byte]))
    if payload:
        hasher.update(payload)
    return hasher.digest()[-4:]


def _encode(protocol: Protocol, is_testnet: bool, payload: bytes) -> str:
    prefix = _prefix_for(protocol, is_testnet)
    raw = bytes([protocol]) + payload + _compute_checksum(protocol, payload)
    return prefix + _base32_encode(raw)


def _base32_encode(data: bytes) -> str:
    result: list[str] = []
    bits = 0
    value = 0
    for byte in data:
        value = (value << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            result.append(_BASE32_ALPHABET[(value >> bits) & 0x1F])
    if bits > 0:
        result.append(_BASE32_ALPHABET[(value << (5 - bits)) & 0x1F])
    return "".join(result)


def _base32_decode(b32_str: str) -> bytes:
    result = bytearray()
    bits = 0
    value = 0
    for char in b32_str:
        index = _BASE32_DECODE_TABLE.get(char)
        if index is None:
            raise ValueError(f"invalid base32 character: {char!r}")
        value = (value << 5) | index
        bits += 5
        if bits >= 8:
            bits -= 8
            result.append((value >> bits) & 0xFF)
    if bits > 0 and (value & ((1 << bits) - 1)):
        raise ValueError(f"trailing bits in base32 string: {b32_str[-1]!r}")
    return bytes(result)


# ---- common valid-looking test addresses for demos ----

# f410 EAM address derived from a well-known Ethereum address pattern
DEMO_F410_PAYER: Final = "f4aqfn5ln657pk3pxp32w35366vw7o7xvnx3xulgbdoa"

# f0 ID address (simulated actor ID for demo purposes)
DEMO_F0_PAYER: Final = "f0aduqoxkizp4a"

DEMO_F410_PAYER_TESTNET: Final = "t4aqfn5ln657pk3pxp32w35366vw7o7xvnx3xulgbdoa"
