import base64
from collections.abc import ByteString
import hashlib
import logging
import random
import re
from typing import Any

from multiaddr import Multiaddr

from ..constants import MAX_MESSAGE_SIZE

_fingerprint_regex = re.compile(
    r"^a=fingerprint:(?:\w+-[0-9]+)\s(?P<fingerprint>(:?([0-9a-fA-F]{2}:?)+))$",
    re.MULTILINE,
)
log = logging.getLogger("libp2p.transport.webrtc")


class SDP:
    """
    Provides utilities for handling SDP modification for direct connections.
    """

    @staticmethod
    def munge_offer(sdp: str, ufrag: str) -> str:
        """
        Munge SDP offer

        Parameters
        ----------
        sdp : str
            The SDP string to be munged.
        ufrag : str
            The ICE username fragment to insert.

        Returns
        -------
        str
            The munged SDP string.

        """
        if sdp is None:
            raise ValueError("Can't munge a missing SDP")

        # Determine line break style
        line_break = "\r\n" if "\r\n" in sdp else "\n"

        # Split SDP into lines for easier manipulation
        lines = sdp.splitlines(keepends=True)
        new_lines = []

        for line in lines:
            if line.startswith("a=ice-ufrag:"):
                new_lines.append(f"a=ice-ufrag:{ufrag}{line_break}")
            elif line.startswith("a=ice-pwd:"):
                new_lines.append(f"a=ice-pwd:{ufrag}{line_break}")
            else:
                new_lines.append(line)

        return "".join(new_lines)

    @staticmethod
    def get_fingerprint_from_sdp(sdp: str | None) -> str | None:
        """
        Extract the DTLS fingerprint from an SDP string.

        Parameters
        ----------
        sdp : str | None
            The SDP string to extract the fingerprint from.

        Returns
        -------
        str | None
            The extracted fingerprint, or None if not found.

        """
        if sdp is None:
            return None
        match = _fingerprint_regex.search(sdp)
        if match and match.group("fingerprint"):
            return match.group("fingerprint")
        return None

    @staticmethod
    def server_answer_from_multiaddr(ma: Multiaddr, ufrag: str) -> dict[str, str]:
        """
        Create an answer SDP message from a multiaddr.
        The server always operates in ice-lite mode and DTLS active mode.

        Parameters
        ----------
        ma : Multiaddr
            The multiaddr to extract host, port, and fingerprint from.
        ufrag : str
            ICE username fragment (also used as password).

        Returns
        -------
        dict[str, str]
            Dictionary with keys 'type' and 'sdp' for RTCSessionDescription.

        """
        # Extract host, port, and family from multiaddr
        opts = extract_from_multiaddr(ma)
        host = opts[0]
        port = opts[1]
        family = opts[2] if opts[2] is not None else 4
        # Convert family to string (4 or 6)
        family_str = str(family)
        # Get fingerprint from multiaddr
        fingerprint = (
            multiaddr_to_fingerprint(ma)
            if "multiaddr_to_fingerprint" in globals()
            else None
        )
        if fingerprint is None:
            raise ValueError("Could not extract fingerprint from multiaddr")
        sdp = (
            f"v=0\r\n"
            f"o=- 0 0 IN IP{family_str} {host}\r\n"
            f"s=-\r\n"
            f"t=0 0\r\n"
            f"a=ice-lite\r\n"
            f"m=application {port} UDP/DTLS/SCTP webrtc-datachannel\r\n"
            f"c=IN IP{family_str} {host}\r\n"
            f"a=mid:0\r\n"
            f"a=ice-options:ice2\r\n"
            f"a=ice-ufrag:{ufrag}\r\n"
            f"a=ice-pwd:{ufrag}\r\n"
            f"a=fingerprint:{fingerprint}\r\n"
            f"a=setup:passive\r\n"
            f"a=sctp-port:5000\r\n"
            f"a=max-message-size:{MAX_MESSAGE_SIZE}\r\n"
            f"a=candidate:1467250027 1 UDP 1467250027 {host} {port} typ host\r\n"
            f"a=end-of-candidates\r\n"
        )
        return {"type": "answer", "sdp": sdp}

    @staticmethod
    def client_offer_from_multiaddr(ma: Multiaddr, ufrag: str) -> dict[str, str]:
        """
        Create an offer SDP message from a multiaddr.

        Parameters
        ----------
        ma : Multiaddr
            The multiaddr to extract host, port, and family from.
        ufrag : str
            ICE username fragment (also used as password).

        Returns
        -------
        dict[str, str]
            Dictionary with keys 'type' and 'sdp' for RTCSessionDescription.

        """
        opts = extract_from_multiaddr(ma)
        host = opts[0]
        port = opts[1]
        family = opts[2] if opts[2] is not None else 4
        family_str = str(family)
        try:
            fingerprint = multiaddr_to_fingerprint(ma)
        except Exception:
            fingerprint = "sha-256 " + ":".join(["00"] * 32)
        sdp = (
            f"v=0\r\n"
            f"o=- 0 0 IN IP{family_str} {host}\r\n"
            f"s=-\r\n"
            f"c=IN IP{family_str} {host}\r\n"
            f"t=0 0\r\n"
            f"a=ice-options:ice2,trickle\r\n"
            f"m=application {port} UDP/DTLS/SCTP webrtc-datachannel\r\n"
            f"a=mid:0\r\n"
            f"a=setup:active\r\n"
            f"a=ice-ufrag:{ufrag}\r\n"
            f"a=ice-pwd:{ufrag}\r\n"
            f"a=fingerprint:{fingerprint}\r\n"
            f"a=sctp-port:5000\r\n"
            f"a=max-message-size:{MAX_MESSAGE_SIZE}\r\n"
            f"a=candidate:1467250027 1 UDP 1467250027 {host} {port} typ host\r\n"
            f"a=end-of-candidates\r\n"
        )
        return {"type": "offer", "sdp": sdp}


def fingerprint_to_multiaddr(fingerprint: str) -> Multiaddr:
    """
    Convert a DTLS fingerprint to a /certhash/ multiaddr.

    Parameters
    ----------
    fingerprint : str
        The DTLS fingerprint as a colon-separated hex string.

    Returns
    -------
    Multiaddr
        The resulting multiaddr with a /certhash/ component.

    """
    if fingerprint is None:
        raise ValueError("Fingerprint is required to build certhash multiaddr")
    fingerprint = fingerprint.strip()
    if " " in fingerprint:
        _, hex_part = fingerprint.split(" ", 1)
    else:
        hex_part = fingerprint
    hex_part = hex_part.replace(":", "").replace(" ", "").upper()
    if not hex_part:
        raise ValueError("Fingerprint hex portion is empty")
    try:
        encoded = bytes.fromhex(hex_part)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid fingerprint hex data: {hex_part}") from exc
    digest = hashlib.sha256(encoded).digest()
    # Multibase base64url, no padding, prefix "uEi" (libp2p convention)
    b64 = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    certhash = f"uEi{b64}"
    return Multiaddr(f"/certhash/{certhash}")


def fingerprint_to_certhash(fingerprint: str) -> str:
    """
    Convert a DTLS fingerprint string to a certhash component.

    Parameters
    ----------
    fingerprint : str
        The DTLS fingerprint as a colon-separated hex string, optionally prefixed
        by the hash algorithm (e.g. "sha-256 AA:BB:...").

    Returns
    -------
    str
        The certhash string (multibase base64url, prefix "uEi").

    """
    certhash_ma = fingerprint_to_multiaddr(fingerprint)
    return extract_certhash(certhash_ma)


def get_hash_function(code: int) -> str:
    """
    Get the hash function name from a multihash code.

    Parameters
    ----------
    code : int
        The multihash code.

    Returns
    -------
    str
        The hash function name (e.g., "sha-256").

    Raises
    ------
    Exception
        If the code is not a supported hash algorithm.

    """
    if code == 0x11:
        return "sha-1"
    elif code == 0x12:
        return "sha-256"
    elif code == 0x13:
        return "sha-512"
    else:
        raise Exception(f"Unsupported hash algorithm code: {code}")


def extract_certhash(ma: Multiaddr) -> str:
    """
    Extract the certhash component from a Multiaddr.

    Parameters
    ----------
    ma : Multiaddr
        The multiaddr to extract the certhash from.

    Returns
    -------
    str
        The certhash string.

    Raises
    ------
    Exception
        If the certhash component is not found.

    """
    for proto in ma.items():
        if proto[0].name == "certhash":
            return proto[1]
    raise Exception(f"Couldn't find a certhash component in: {str(ma)}")


def canonicalize_certhash(ma: Multiaddr, certhash: str) -> Multiaddr:
    """
    Ensure a multiaddr contains the provided certhash component in canonical form.

    The function preserves the original protocol ordering, replacing the existing
    certhash value if present, or inserting the new certhash immediately before the
    trailing /p2p component if one exists (to match libp2p expectations).
    """

    def _value_to_str(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return value.hex()
        return str(value)

    protocols_list = list(ma.protocols())
    values_list = list(ma.values())

    has_certhash = any(proto.name == "certhash" for proto in protocols_list)
    parts: list[str] = []
    inserted = False

    for proto, value in zip(protocols_list, values_list):
        name = proto.name
        if name == "certhash":
            value_str = certhash
        else:
            value_str = _value_to_str(value)
        if not has_certhash and not inserted and name == "p2p":
            parts.append(f"/certhash/{certhash}")
            inserted = True

        if value_str == "":
            parts.append(f"/{name}")
        else:
            parts.append(f"/{name}/{value_str}")

    if not has_certhash and not inserted:
        parts.append(f"/certhash/{certhash}")

    return Multiaddr("".join(parts))


def certhash_encode(s: str) -> tuple[int, bytes]:
    """
    Encode a certificate hash component from a certhash string.

    Parameters
    ----------
    s : str
        The certhash string to encode.

    Returns
    -------
    tuple[int, bytes]
        A tuple containing the multihash code and the digest bytes.

    Raises
    ------
    Exception
        If the input is empty, invalid, or the digest length is incorrect.

    """
    if not s:
        raise Exception("Empty certhash string.")

    # Remove multibase prefix if present
    if s.startswith("uEi"):
        s = s[3:]
    elif s.startswith("u"):
        s = s[1:]

    # Decode base64url encoded hash
    try:
        s_bytes = s.encode("ascii")
        # Add padding if needed
        padding = 4 - (len(s_bytes) % 4)
        if padding != 4:
            s_bytes += b"=" * padding
        raw_bytes = base64.urlsafe_b64decode(s_bytes)
    except Exception as e:
        raise Exception("Invalid base64url certhash") from e

    if len(raw_bytes) < 2:
        raise Exception("Decoded certhash is too short to contain multihash header")

    # Multihash format: <code><length><digest>
    code = raw_bytes[0]
    length = raw_bytes[1]
    digest = raw_bytes[2:]

    if len(digest) != length:
        raise Exception(f"Digest length mismatch: expected {length}, got {len(digest)}")

    return code, digest


def certhash_decode(b: ByteString) -> str:
    """
    Decode a certificate hash component to a certhash string.

    Parameters
    ----------
    b : ByteString
        The digest bytes to encode.

    Returns
    -------
    str
        The certhash string (multibase base64url, prefix "uEi").

    """
    if not b:
        return ""

    # Encode as base64url and add multibase prefix
    b64_hash = base64.urlsafe_b64encode(b).decode().rstrip("=")
    return f"uEi{b64_hash}"


def multiaddr_to_fingerprint(ma: Multiaddr) -> str:
    """
    Extract the fingerprint from a Multiaddr containing a certhash.

    Parameters
    ----------
    ma : Multiaddr
        The multiaddr containing a /certhash/ component.

    Returns
    -------
    str
        The fingerprint string in SDP format.

    Raises
    ------
    Exception
        If the fingerprint cannot be extracted.

    """
    certhash_str = extract_certhash(ma)
    code, digest = certhash_encode(certhash_str)
    prefix = get_hash_function(int(code))
    hex_digest = digest.hex()
    sdp = [hex_digest[i : i + 2].upper() for i in range(0, len(hex_digest), 2)]

    if not sdp:
        raise Exception(hex_digest, str(ma))

    return f"{prefix} {':'.join(sdp)}"


def pick_random_ice_servers(
    ice_servers: list[dict[str, Any]], num_servers: int = 4
) -> list[dict[str, Any]]:
    """
    Select a random subset of ICE servers for load distribution.

    Parameters
    ----------
    ice_servers : list[dict[str, Any]]
        The list of ICE server dictionaries.
    num_servers : int, optional
        The number of servers to select (default is 4).

    Returns
    -------
    list[dict[str, Any]]
        The randomly selected subset of ICE servers.

    """
    random.shuffle(ice_servers)
    return ice_servers[:num_servers]


def generate_ufrag(length: int = 4) -> str:
    """
    Generate a random username fragment (ufrag) for SDP munging.

    Parameters
    ----------
    length : int, optional
        The length of the generated ufrag (default is 4).

    Returns
    -------
    str
        The generated ufrag string.

    """
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    return "".join(random.choices(alphabet, k=length))


def extract_from_multiaddr(ma: Multiaddr) -> tuple[str, int, int | None]:
    """
    Convert a Multiaddr to a tuple with host, port, and IP family.

    Parameters
    ----------
    ma : Multiaddr
        The multiaddr to convert.

    Returns
    -------
    Tuple[str, int, Optional[int]]
        Tuple with (host, port, family).

    Raises
    ------
    Exception
        If the multiaddr is missing an IP or port.

    """
    protocols = ma.protocols()
    values = ma.values()

    ip = None
    port = None
    family = None

    for proto, val in zip(protocols, values):
        if proto.name == "ip4":
            ip = val
            family = 4
        elif proto.name == "ip6":
            ip = val
            family = 6
        elif proto.name == "udp":
            port = int(val)

    if ip is None or port is None:
        raise Exception(f"Invalid multiaddr, missing ip/port: {str(ma)}")

    return str(ip), port, family


def generate_noise_prologue(
    local_fingerprint: str, remote_multi_addr: Multiaddr, role: str
) -> bytes:
    """
    Generate a noise prologue from the peer connection's certificate.

    Parameters
    ----------
    local_fingerprint : str
        The local DTLS fingerprint (colon-separated hex string).
    remote_multi_addr : Multiaddr
        The remote peer's multiaddr (should contain /certhash/).
    role : str
        Either 'client' or 'server'.

    Returns
    -------
    bytes
        The noise prologue as bytes.

    """
    # noise prologue =
    # bytes('libp2p-webrtc-noise:') +noise-server fingerprint +noise-client fingerprint
    PREFIX = b"libp2p-webrtc-noise:"

    local_fp_string = local_fingerprint.strip().lower().replace(":", "")
    local_fp_bytes = bytes.fromhex(local_fp_string)
    local_digest = hashlib.sha256(local_fp_bytes).digest()

    cert = extract_certhash(remote_multi_addr)
    _, remote_bytes = certhash_encode(cert)

    if role == "server":
        # server: PREFIX + remote + local
        return PREFIX + remote_bytes + local_digest
    else:
        # client: PREFIX + local + remote
        return PREFIX + local_digest + remote_bytes
