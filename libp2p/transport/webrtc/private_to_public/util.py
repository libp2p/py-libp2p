import base64
from collections.abc import ByteString
import logging
import random
import re
from typing import Any

from multiaddr import Multiaddr

from ..constants import MAX_MESSAGE_SIZE

_fingerprint_regex = re.compile(
    r"^a=fingerprint:(?:\w+-[0-9]+)\s(?P<fingerprint>(?:[0-9A-Fa-f]{2}:)*[0-9A-Fa-f]{2})\r?$",
    re.MULTILINE,
)
logger = logging.getLogger("libp2p.transport.webrtc.private_to_public.util")


class SDP:
    """
    Provides utilities for handling SDP modification for direct connections.
    """

    @staticmethod
    def munge_offer(sdp: str, ufrag: str, ice_pwd: str) -> str:
        """
        Munge SDP offer

        Parameters
        ----------
        sdp : str
            The SDP string to be munged.
        ufrag : str
            The ICE username fragment to insert.
        ice_pwd : str
            The ICE password to insert (must satisfy RFC 8445 length requirements).

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
                new_lines.append(f"a=ice-pwd:{ice_pwd}{line_break}")
            else:
                new_lines.append(line)

        return "".join(new_lines)

    @staticmethod
    def get_ice_credentials_from_sdp(sdp: str | None) -> tuple[str | None, str | None]:
        """Extract ice-ufrag and ice-pwd from SDP. Returns (ufrag, ice_pwd)."""
        if not sdp:
            return None, None
        ufrag, ice_pwd = None, None
        for line in sdp.splitlines():
            if line.startswith("a=ice-ufrag:"):
                ufrag = line.split(":", 1)[1].strip()
            elif line.startswith("a=ice-pwd:"):
                ice_pwd = line.split(":", 1)[1].strip()
        return ufrag, ice_pwd

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
    # Create full multihash bytes: code (0x12 for sha-256) + length + digest
    # This matches js-libp2p: Digest.create(sha256.code, encoded).bytes
    digest_len = len(encoded)
    if digest_len == 32:
        # SHA-256: code 0x12, length 32 (0x20)
        multihash_bytes = bytes([0x12, 0x20]) + encoded
    elif digest_len == 20:
        # SHA-1: code 0x11, length 20 (0x14)
        multihash_bytes = bytes([0x11, 0x14]) + encoded
    elif digest_len == 64:
        # SHA-512: code 0x13, length 64 (0x40)
        multihash_bytes = bytes([0x13, 0x40]) + encoded
    else:
        raise ValueError(f"Unsupported digest length: {digest_len}")
    # Base64url encode the full multihash bytes
    # Note: "u" is the multibase prefix for base64url
    # The base64url encoding naturally starts with "Ei" (encoding of [0x12, 0x20])
    # So we should NOT add "Ei" as a prefix - just use "u" prefix
    b64 = base64.urlsafe_b64encode(multihash_bytes).decode("utf-8").rstrip("=")
    certhash = f"u{b64}"
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

    # Try multihash format: <code><length><digest>
    if len(raw_bytes) >= 2:
        code = raw_bytes[0]
        length = raw_bytes[1]
        digest = raw_bytes[2:]
        if len(digest) == length:
            return code, digest

    # Fallback: treat entire payload as digest (legacy format)
    digest = raw_bytes
    digest_len = len(digest)
    if digest_len == 20:
        code = 0x11  # sha-1
    elif digest_len == 32:
        code = 0x12  # sha-256
    elif digest_len == 64:
        code = 0x13  # sha-512
    else:
        raise Exception(f"Unsupported certhash digest length: {digest_len}")

    return code, digest


def certhash_decode(b: ByteString) -> str:
    """
    Decode a certificate hash component to a certhash string.

    Parameters
    ----------
    b : ByteString
        The digest bytes to encode (should be 32 bytes for SHA-256).

    Returns
    -------
    str
        The certhash string (multibase base64url, prefix "u").

    """
    if not b:
        return ""

    # Create full multihash bytes: code + length + digest
    digest_len = len(b)
    if digest_len == 32:
        multihash_bytes = bytes([0x12, 0x20]) + b
    elif digest_len == 20:
        multihash_bytes = bytes([0x11, 0x14]) + b
    elif digest_len == 64:
        multihash_bytes = bytes([0x13, 0x40]) + b
    else:
        raise ValueError(f"Unsupported digest length: {digest_len}")

    # Base64url encode the full multihash bytes
    # Note: "u" is the multibase prefix for base64url
    # The base64url encoding naturally starts with "Ei" (encoding of [0x12, 0x20])
    b64_hash = base64.urlsafe_b64encode(multihash_bytes).decode().rstrip("=")
    return f"u{b64_hash}"


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


ICE_ALLOWED_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789+/"


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
    if length < 4:
        raise ValueError("ICE ufrag length must be at least 4 characters")
    alphabet = ICE_ALLOWED_CHARS
    return "".join(random.choices(alphabet, k=length))


def generate_ice_credentials(
    ufrag_length: int = 16, pwd_length: int = 32
) -> tuple[str, str]:
    """
    Generate ICE username fragment and password.

    For WebRTC-Direct (browser-to-server style), we use the same value for ufrag and
    password to allow the listener side to correlate the session without requiring an
    out-of-band signaling channel.

    The ICE password MUST be between 22 and 256 characters. The ufrag must be at least 4
    characters.
    """
    prefix = "libp2p+webrtc+v1/"
    # Ensure we satisfy RFC 8445 minimum password length.
    target_len = max(ufrag_length, pwd_length, 22)
    suffix_len = max(target_len - len(prefix), 4)
    ufrag = prefix + generate_ufrag(suffix_len)
    return ufrag, ufrag


def is_localhost_address(ip: str) -> bool:
    """
    Check if an IP address is a localhost/loopback address.

    Parameters
    ----------
    ip : str
        The IP address to check.

    Returns
    -------
    bool
        True if the address is localhost/loopback, False otherwise.

    """
    if not ip:
        return False
    ip_lower = ip.lower().strip()
    return ip_lower in ("127.0.0.1", "::1", "localhost", "0.0.0.0", "::")


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

    This matches the js-libp2p implementation:
    - PREFIX = 'libp2p-webrtc-noise:'
    - local = SHA256(local fingerprint bytes) as multihash digest
    - remote = decoded certhash from multiaddr as multihash digest
    - server: PREFIX + remote + local
    - client: PREFIX + local + remote

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

    # Extract local fingerprint bytes (remove "sha-256 " prefix if present)
    local_fp_string = local_fingerprint.strip().lower()
    if " " in local_fp_string:
        # Remove algorithm prefix (e.g. "sha-256 ")
        _, hex_part = local_fp_string.split(" ", 1)
    else:
        hex_part = local_fp_string
    # Remove colons and convert to bytes
    hex_part = hex_part.replace(":", "").replace(" ", "")
    local_fp_bytes = bytes.fromhex(hex_part)

    # The DTLS fingerprint value is already a hash digest of the certificate.
    # For the Noise prologue, we need the multihash framing (code + length + digest)
    # around that digest - we MUST NOT hash it again.
    if len(local_fp_bytes) != 32:
        raise ValueError(
            f"Unsupported local fingerprint length: {len(local_fp_bytes)} bytes"
        )
    # sha2-256 multihash framing: code 0x12, length 0x20 (32 bytes)
    local_multihash = bytes([0x12, 0x20]) + local_fp_bytes

    # Extract remote certhash and decode to get FULL multihash bytes
    # This matches js-libp2p: sdp.multibaseDecoder.decode(sdp.certhash(remoteAddr))
    # The certhash is multibase-encoded: "u" prefix means base64url encoding
    # The encoded content is the FULL multihash bytes (code + length + digest)
    cert = extract_certhash(remote_multi_addr)
    # Decode multibase: "u" is the base64url prefix, rest is base64url-encoded multihash
    # Note: "Ei" is NOT part of the prefix - it's the base64url encoding of [0x12, 0x20]
    # So even if certhash starts with "uEi", we should only remove "u" prefix
    if cert.startswith("u"):
        base64_part = cert[1:]  # Remove "u" multibase prefix only
    else:
        base64_part = cert

    # Decode base64url to get full multihash bytes (code + length + digest)
    try:
        s_bytes = base64_part.encode("ascii")
        padding = 4 - (len(s_bytes) % 4)
        if padding != 4:
            s_bytes += b"=" * padding
        remote_multihash = base64.urlsafe_b64decode(s_bytes)
        # Verify it's a valid multihash (should start with code + length)
        if len(remote_multihash) < 2:
            raise Exception(
                f"Decoded certhash too short: {len(remote_multihash)} bytes"
            )
        # Verify it's SHA-256 multihash (code 0x12, length should match digest)
        if remote_multihash[0] != 0x12:
            raise Exception(
                f"Invalid multihash code: expected 0x12 (SHA-256), "
                f"got {remote_multihash[0]:#x}"
            )
        expected_digest_len = remote_multihash[1]
        actual_digest_len = len(remote_multihash[2:])
        if actual_digest_len != expected_digest_len:
            raise Exception(
                f"Invalid multihash length: expected {expected_digest_len} "
                f"bytes digest, got {actual_digest_len} bytes"
            )
        if expected_digest_len != 32:
            raise Exception(
                f"Unsupported digest length: expected 32 bytes (SHA-256), "
                f"got {expected_digest_len} bytes"
            )
    except Exception as e:
        raise Exception(f"Failed to decode certhash '{cert}': {e}") from e

    if role == "server":
        # server: PREFIX + remote + local
        prologue = PREFIX + remote_multihash + local_multihash
    else:
        # client: PREFIX + local + remote
        prologue = PREFIX + local_multihash + remote_multihash

    logger.debug(
        f"Generated noise prologue for {role}: "
        f"local_multihash_len={len(local_multihash)}, "
        f"remote_multihash_len={len(remote_multihash)}, "
        f"prologue_len={len(prologue)}"
    )
    # Debug: log first few bytes to verify format
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            f"Prologue bytes (first 50): {prologue[:50].hex()} "
            f"local_mh_header={local_multihash[:2].hex()} "
            f"remote_mh_header={remote_multihash[:2].hex()}"
        )
    return prologue
