from collections.abc import Callable
import json
import logging
import random
import re
from typing import (
    Any,
    Tuple
)
import base64
import re
import hashlib
from multiaddr import Multiaddr
from libp2p.abc import (
    IHost,
    TProtocol,
)
from ..constants import (MAX_MESSAGE_SIZE)
from collections.abc import ByteString

_fingerprint_regex = re.compile(
    r"^a=fingerprint:(?:\w+-[0-9]+)\s(?P<fingerprint>(:?([0-9a-fA-F]{2}:?)+))$",
    re.MULTILINE,
)
log = logging.getLogger("libp2p.transport.webrtc")



class SDP:
    """
    Handle SDP modification for direct connections
    """

    @staticmethod
    def munge_offer(sdp: str, ufrag: str) -> str:
        """
        Munge SDP offer

        Parameters
        ----------
        sdp : str
        ufrag : str

        Returns
        -------
        str
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

        Returns
        -------
        str | None
        """
        if sdp is None:
            return None
        match = _fingerprint_regex.search(sdp)
        if match and match.group("fingerprint"):
            return match.group("fingerprint")
        return None
    
    @staticmethod
    def server_answer_from_multiaddr(ma, ufrag: str) -> dict:
        """
        Create an answer SDP message from a multiaddr.
        The server always operates in ice-lite mode and DTLS active mode.

        Parameters
        ----------
        ma : Multiaddr
            The multiaddr to extract host, port, and fingerprint from.
        ufrag : str
            ICE username fragment (also used as password).
        max_message_size : int
            Maximum SCTP message size (default: 65536).

        Returns
        -------
        dict
            Dictionary with keys 'type' and 'sdp' for RTCSessionDescription.
        """
        # Extract host, port, and family from multiaddr
        opts = extract_from_multiaddr(ma)
        host = opts.get("host")
        port = opts.get("port")
        family = opts.get("family", 4)
        # Convert family to string (4 or 6)
        family_str = str(family)
        # Get fingerprint from multiaddr
        fingerprint = multiaddr_to_fingerprint(ma) if "multiaddr_to_fingerprint" in globals() else None
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
        return {
            "type": "answer",
            "sdp": sdp
        }

    @staticmethod
    def client_offer_from_multiaddr(ma, ufrag: str) -> dict:
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
        dict
            Dictionary with keys 'type' and 'sdp' for RTCSessionDescription.
        """
        opts = extract_from_multiaddr(ma)
        host = opts.get("host")
        port = opts.get("port")
        family = opts.get("family", 4)
        family_str = str(family)
        # Use a dummy fingerprint as in the TS code
        dummy_fingerprint = "sha-256 " + ":".join(["00"] * 32)
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
            f"a=fingerprint:{dummy_fingerprint}\r\n"
            f"a=sctp-port:5000\r\n"
            f"a=max-message-size:{MAX_MESSAGE_SIZE}\r\n"
            f"a=candidate:1467250027 1 UDP 1467250027 {host} {port} typ host\r\n"
            f"a=end-of-candidates\r\n"
        )
        return {
            "type": "offer",
            "sdp": sdp
        }

def fingerprint_to_multiaddr(fingerprint: str) -> Multiaddr:
    """
    Convert a DTLS fingerprint to a /certhash/ multiaddr.

    Parameters
    ----------
    fingerprint : str

    Returns
    -------
    Multiaddr
    """
    
    fingerprint = fingerprint.strip().replace(" ", "").upper()
    parts = fingerprint.split(":")
    encoded = bytes(int(part, 16) for part in parts)
    digest = hashlib.sha256(encoded).digest()
    
    # Multibase base64url, no padding, prefix "uEi" (libp2p convention)
    b64 = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    certhash = f"uEi{b64}"
    return Multiaddr(f"/certhash/{certhash}")

def get_hash_function(code: int) -> str:
    """
    Get hash function name from code.

    Parameters
    ----------
    code : int

    Returns
    -------
    str
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
    Extract certhash component from Multiaddr.

    Parameters
    ----------
    ma : Multiaddr

    Returns
    -------
    str
    """
    for proto in ma.protocols_with_values():
        if proto[0].name == "certhash":
            return proto[1]
    raise Exception(f"Couldn't find a certhash component in: {str(ma)}")

def certhash_encode(s: str) -> Tuple[int, bytes]:
    """
    Encode certificate hash component.

    Parameters
    ----------
    s : str

    Returns
    -------
    Tuple[int, bytes]
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
    Decode certificate hash component.

    Parameters
    ----------
    b : ByteString

    Returns
    -------
    str
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

    Returns
    -------
    str

    Raises
    ------
    Exception
    """
    certhash_str = extract_certhash(ma)
    code, digest = certhash_decode(certhash_str)
    prefix = get_hash_function(code)
    hex_digest = digest.hex()
    sdp = [hex_digest[i:i+2].upper() for i in range(0, len(hex_digest), 2)]

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
    num_servers : int, default=4

    Returns
    -------
    list[dict[str, Any]]
    """
    random.shuffle(ice_servers)
    return ice_servers[:num_servers]


def generate_ufrag(length: int = 4) -> str:
    """
    Generate a random username fragment (ufrag) for SDP munging.

    Parameters
    ----------
    length : int, default=4

    Returns
    -------
    str
    """
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    return "".join(random.choices(alphabet, k=length))

from multiaddr import Multiaddr

def extract_from_multiaddr(ma: Multiaddr) -> dict:
    """
    Convert a Multiaddr to a dictionary with host, port, and IP family.

    Parameters
    ----------
    ma : Multiaddr
        The multiaddr to convert.

    Returns
    -------
    dict
        Dictionary with keys 'host', 'port', and 'family'.
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

    return {
        "host": ip,
        "port": port,
        "family": family
    }


def generate_noise_prologue(local_fingerprint: str, remote_multi_addr: Multiaddr, role: str) -> bytes:
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
    # noise prologue = bytes('libp2p-webrtc-noise:') + noise-server fingerprint + noise-client fingerprint
    PREFIX = b'libp2p-webrtc-noise:'

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
