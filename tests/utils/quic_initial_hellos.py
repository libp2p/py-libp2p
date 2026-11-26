"""
Read the TLS ClientHello and ServerHello from QUIC v1 Initial packets.

Initial packets are protected with keys derived from the Destination
Connection ID of the client's first packet and a salt fixed by the QUIC
version (RFC 9001 section 5.2). Anyone who sees the datagrams can therefore
read the two hello messages, which is what lets a test check the negotiated
key exchange group without reaching into the QUIC library.

Only what such a test needs is decoded: the groups and key shares of each
ClientHello, and the group of each ServerHello.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

Direction = Literal["client_to_server", "server_to_client"]

QUIC_V1 = 0x00000001
INITIAL_SALT_V1 = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
# A ServerHello with this random value is a HelloRetryRequest (RFC 8446 4.1.3).
HELLO_RETRY_REQUEST_RANDOM = bytes.fromhex(
    "cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c"
)

PACKET_TYPE_INITIAL = 0
PACKET_TYPE_RETRY = 3

FRAME_PADDING = 0x00
FRAME_PING = 0x01
FRAME_ACK = 0x02
FRAME_ACK_ECN = 0x03
FRAME_CRYPTO = 0x06
FRAME_CONNECTION_CLOSE = 0x1C

HANDSHAKE_CLIENT_HELLO = 1
HANDSHAKE_SERVER_HELLO = 2

EXTENSION_SUPPORTED_GROUPS = 0x000A
EXTENSION_KEY_SHARE = 0x0033

AES_128_KEY_LENGTH = 16
AEAD_IV_LENGTH = 12
SHA256_LENGTH = 32
# Header protection samples 16 bytes starting 4 bytes after the start of the
# packet number field (RFC 9001 section 5.4.2).
HEADER_PROTECTION_SAMPLE_OFFSET = 4
HEADER_PROTECTION_SAMPLE_LENGTH = 16


@dataclass(frozen=True)
class ClientHelloGroups:
    """Key exchange groups in one ClientHello, as NamedGroup code points."""

    # In the client's order of preference.
    supported_groups: tuple[int, ...]
    # The groups the client sent a key share for.
    key_share_groups: tuple[int, ...]


@dataclass(frozen=True)
class ServerHelloGroup:
    """The group one ServerHello or HelloRetryRequest names."""

    selected_group: int | None
    is_hello_retry_request: bool


@dataclass(frozen=True)
class ObservedHellos:
    client_hellos: tuple[ClientHelloGroups, ...]
    server_hellos: tuple[ServerHelloGroup, ...]


@dataclass(frozen=True)
class InitialKeys:
    key: bytes
    iv: bytes
    header_protection: bytes


@dataclass(frozen=True)
class _LongHeaderPacket:
    packet_type: int
    destination_cid: bytes
    source_cid: bytes
    # The whole packet, and where its packet number field starts.
    raw: bytes
    packet_number_offset: int


def _hkdf_expand_label(secret: bytes, label: str, length: int) -> bytes:
    full_label = b"tls13 " + label.encode()
    info = length.to_bytes(2, "big") + bytes([len(full_label)]) + full_label + b"\x00"
    return HKDFExpand(hashes.SHA256(), length, info).derive(secret)


def derive_initial_keys(
    original_destination_cid: bytes, sender: Literal["client", "server"]
) -> InitialKeys:
    """Derive the Initial packet protection keys of one endpoint."""
    extract = HMAC(INITIAL_SALT_V1, hashes.SHA256())
    extract.update(original_destination_cid)
    initial_secret = extract.finalize()
    secret = _hkdf_expand_label(initial_secret, f"{sender} in", SHA256_LENGTH)
    return InitialKeys(
        key=_hkdf_expand_label(secret, "quic key", AES_128_KEY_LENGTH),
        iv=_hkdf_expand_label(secret, "quic iv", AEAD_IV_LENGTH),
        header_protection=_hkdf_expand_label(secret, "quic hp", AES_128_KEY_LENGTH),
    )


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    length = 1 << (buf[pos] >> 6)
    value = buf[pos] & 0x3F
    for byte in buf[pos + 1 : pos + length]:
        value = (value << 8) | byte
    return value, pos + length


def _read_connection_id(buf: bytes, pos: int) -> tuple[bytes, int]:
    """Read a connection ID with its one-byte length prefix."""
    end = pos + 1 + buf[pos]
    return buf[pos + 1 : end], end


def _long_header_packets(datagram: bytes) -> Iterator[_LongHeaderPacket]:
    """Yield the coalesced long-header packets at the start of a datagram."""
    pos = 0
    while pos < len(datagram) and datagram[pos] & 0x80:
        start = pos
        packet_type = (datagram[pos] & 0x30) >> 4
        version = int.from_bytes(datagram[pos + 1 : pos + 5], "big")
        if version != QUIC_V1:
            raise ValueError(f"QUIC version {version:#010x} is not supported")
        destination_cid, pos = _read_connection_id(datagram, pos + 5)
        source_cid, pos = _read_connection_id(datagram, pos)
        if packet_type == PACKET_TYPE_RETRY:
            # A Retry packet has no length field and ends the datagram.
            yield _LongHeaderPacket(
                packet_type, destination_cid, source_cid, datagram[start:], 0
            )
            return
        if packet_type == PACKET_TYPE_INITIAL:
            token_length, pos = _read_varint(datagram, pos)
            pos += token_length
        length, pos = _read_varint(datagram, pos)
        yield _LongHeaderPacket(
            packet_type,
            destination_cid,
            source_cid,
            datagram[start : pos + length],
            pos - start,
        )
        pos += length


def _decrypt_initial(packet: _LongHeaderPacket, keys: InitialKeys) -> bytes:
    raw = packet.raw
    pn_offset = packet.packet_number_offset
    sample_start = pn_offset + HEADER_PROTECTION_SAMPLE_OFFSET
    sample = raw[sample_start : sample_start + HEADER_PROTECTION_SAMPLE_LENGTH]
    encryptor = Cipher(algorithms.AES(keys.header_protection), modes.ECB()).encryptor()
    mask = encryptor.update(sample) + encryptor.finalize()

    # Header protection covers the low four bits of the first byte, which
    # hold the packet number length, and the packet number itself.
    first_byte = raw[0] ^ (mask[0] & 0x0F)
    packet_number_length = (first_byte & 0x03) + 1
    header_end = pn_offset + packet_number_length
    packet_number = bytes(a ^ b for a, b in zip(raw[pn_offset:header_end], mask[1:]))
    header = bytes([first_byte]) + raw[1:pn_offset] + packet_number

    nonce = bytes(
        a ^ b for a, b in zip(keys.iv, packet_number.rjust(AEAD_IV_LENGTH, b"\x00"))
    )
    return AESGCM(keys.key).decrypt(nonce, raw[header_end:], header)


def _crypto_frames(payload: bytes) -> list[tuple[int, bytes]]:
    """Return ``(offset, data)`` for each CRYPTO frame in an Initial payload."""
    frames: list[tuple[int, bytes]] = []
    pos = 0
    while pos < len(payload):
        frame_type = payload[pos]
        pos += 1
        if frame_type in (FRAME_PADDING, FRAME_PING):
            continue
        if frame_type in (FRAME_ACK, FRAME_ACK_ECN):
            _, pos = _read_varint(payload, pos)  # largest acknowledged
            _, pos = _read_varint(payload, pos)  # ack delay
            range_count, pos = _read_varint(payload, pos)
            _, pos = _read_varint(payload, pos)  # first ack range
            for _ in range(2 * range_count):  # gap and length of each range
                _, pos = _read_varint(payload, pos)
            if frame_type == FRAME_ACK_ECN:
                for _ in range(3):
                    _, pos = _read_varint(payload, pos)
        elif frame_type == FRAME_CRYPTO:
            offset, pos = _read_varint(payload, pos)
            length, pos = _read_varint(payload, pos)
            frames.append((offset, payload[pos : pos + length]))
            pos += length
        elif frame_type == FRAME_CONNECTION_CLOSE:
            # Nothing after it matters; the caller sees a missing hello.
            break
        else:
            raise ValueError(f"unexpected frame type {frame_type:#04x} in Initial")
    return frames


def _reassemble(frames: list[tuple[int, bytes]]) -> bytes:
    """Join CRYPTO frames by offset. Retransmitted data overwrites itself."""
    stream = bytearray()
    for offset, data in sorted(frames):
        if offset > len(stream):
            raise ValueError(f"CRYPTO data missing before offset {offset}")
        stream[offset : offset + len(data)] = data
    return bytes(stream)


def _handshake_messages(stream: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield ``(type, body)`` for each complete handshake message."""
    pos = 0
    while pos + 4 <= len(stream):
        length = int.from_bytes(stream[pos + 1 : pos + 4], "big")
        if pos + 4 + length > len(stream):
            return
        yield stream[pos], stream[pos + 4 : pos + 4 + length]
        pos += 4 + length


def _extensions(buf: bytes) -> dict[int, bytes]:
    extensions: dict[int, bytes] = {}
    pos = 0
    while pos + 4 <= len(buf):
        extension_type = int.from_bytes(buf[pos : pos + 2], "big")
        length = int.from_bytes(buf[pos + 2 : pos + 4], "big")
        extensions[extension_type] = buf[pos + 4 : pos + 4 + length]
        pos += 4 + length
    return extensions


def _parse_client_hello(body: bytes) -> ClientHelloGroups:
    pos = 2 + 32  # legacy_version, random
    pos += 1 + body[pos]  # legacy_session_id
    pos += 2 + int.from_bytes(body[pos : pos + 2], "big")  # cipher_suites
    pos += 1 + body[pos]  # legacy_compression_methods
    extensions = _extensions(body[pos + 2 :])

    groups = extensions.get(EXTENSION_SUPPORTED_GROUPS, b"")
    supported_groups = tuple(
        int.from_bytes(groups[i : i + 2], "big") for i in range(2, len(groups), 2)
    )

    key_share_groups: list[int] = []
    shares = extensions.get(EXTENSION_KEY_SHARE, b"")
    share_pos = 2
    while share_pos + 4 <= len(shares):
        key_share_groups.append(
            int.from_bytes(shares[share_pos : share_pos + 2], "big")
        )
        share_length = int.from_bytes(shares[share_pos + 2 : share_pos + 4], "big")
        share_pos += 4 + share_length
    return ClientHelloGroups(supported_groups, tuple(key_share_groups))


def _parse_server_hello(body: bytes) -> ServerHelloGroup:
    random = body[2:34]
    pos = 2 + 32
    pos += 1 + body[pos]  # legacy_session_id_echo
    pos += 2 + 1  # cipher_suite, legacy_compression_method
    # The key_share extension starts with the group in a ServerHello and is
    # only the group in a HelloRetryRequest.
    key_share = _extensions(body[pos + 2 :]).get(EXTENSION_KEY_SHARE, b"")
    return ServerHelloGroup(
        selected_group=int.from_bytes(key_share[:2], "big") if key_share else None,
        is_hello_retry_request=random == HELLO_RETRY_REQUEST_RANDOM,
    )


def observe_hellos(datagrams: Iterable[tuple[Direction, bytes]]) -> ObservedHellos:
    """
    Decode the hello messages from the datagrams of one QUIC connection.

    ``datagrams`` are the UDP payloads in the order they were seen, each with
    the direction it travelled in. Packets other than Initial are skipped.
    """
    frames: dict[Direction, list[tuple[int, bytes]]] = {
        "client_to_server": [],
        "server_to_client": [],
    }
    original_destination_cid: bytes | None = None

    for direction, datagram in datagrams:
        for packet in _long_header_packets(datagram):
            if packet.packet_type == PACKET_TYPE_RETRY:
                # The client starts over, keyed by the server's new
                # connection ID (RFC 9001 section 5.2).
                original_destination_cid = packet.source_cid
                frames["client_to_server"].clear()
                continue
            if packet.packet_type != PACKET_TYPE_INITIAL:
                continue
            from_client = direction == "client_to_server"
            if original_destination_cid is None:
                if not from_client:
                    raise ValueError("server Initial seen before any client Initial")
                original_destination_cid = packet.destination_cid
            keys = derive_initial_keys(
                original_destination_cid, "client" if from_client else "server"
            )
            frames[direction].extend(_crypto_frames(_decrypt_initial(packet, keys)))

    client_stream = _reassemble(frames["client_to_server"])
    server_stream = _reassemble(frames["server_to_client"])
    return ObservedHellos(
        client_hellos=tuple(
            _parse_client_hello(body)
            for message_type, body in _handshake_messages(client_stream)
            if message_type == HANDSHAKE_CLIENT_HELLO
        ),
        server_hellos=tuple(
            _parse_server_hello(body)
            for message_type, body in _handshake_messages(server_stream)
            if message_type == HANDSHAKE_SERVER_HELLO
        ),
    )
