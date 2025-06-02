import base64
import datetime
import hashlib
from typing import (
    Optional,
)

from aiortc import (
    RTCCertificate,
)
import base58
from cryptography import (
    x509,
)
from cryptography.hazmat.backends import (
    default_backend,
)
from cryptography.hazmat.primitives import (
    hashes,
    serialization,
)
from cryptography.hazmat.primitives.asymmetric import (
    rsa,
)
from cryptography.x509.oid import (
    NameOID,
)
from multiaddr import (
    Multiaddr,
)

from libp2p.peer.id import (
    ID,
)

SIGNAL_PROTOCOL = "/libp2p/webrtc/signal/1.0.0"


class CertificateManager(RTCCertificate):
    def __init__(self):
        self.x509 = None
        self.private_key = None
        self.certificate = None
        self.certhash = None

    def generate_self_signed_cert(self, common_name: str = "py-libp2p") -> None:
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
        )
        self.certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(self.private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .sign(self.private_key, hashes.SHA256())
        )
        self.certhash = self._compute_certhash(self.certificate)

    def _compute_certhash(self, cert: x509.Certificate) -> str:
        # Encode in DER format and compute SHA-256 hash
        der_bytes = cert.public_bytes(serialization.Encoding.DER)
        sha256_hash = hashlib.sha256(der_bytes).digest()
        return base64.urlsafe_b64encode(sha256_hash).decode("utf-8").rstrip("=")

    def get_certhash(self) -> str:
        # return self.certhash
        return f"uEi{self.certhash}"

    def get_certificate_pem(self) -> bytes:
        return self.certificate.public_bytes(serialization.Encoding.PEM)

    def get_private_key_pem(self) -> bytes:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )


class SDPMunger:
    """Handle SDP modification for direct connections"""

    @staticmethod
    def munge_offer(sdp: str, ip: str, port: int) -> str:
        """Modify SDP offer for direct connection"""
        lines = sdp.split("\n")
        munged = []

        for line in lines:
            if line.startswith("a=candidate"):
                # Modify ICE candidate to use provided IP/port
                parts = line.split()
                parts[4] = ip
                parts[5] = str(port)
                line = " ".join(parts)
            munged.append(line)

        return "\n".join(munged)

    @staticmethod
    def munge_answer(sdp: str, ip: str, port: int) -> str:
        """Modify SDP answer for direct connection"""
        return SDPMunger.munge_offer(sdp, ip, port)


def create_webrtc_multiaddr(
    ip: str, peer_id: ID, certhash: str, direct: bool = False
) -> Multiaddr:
    """Create WebRTC multiaddr with proper format"""
    # For direct connections
    if direct:
        return Multiaddr(
            f"/ip4/{ip}/udp/0/webrtc-direct" f"/certhash/{certhash}" f"/p2p/{peer_id}"
        )

    # For signaled connections
    return Multiaddr(f"/ip4/{ip}/webrtc" f"/certhash/{certhash}" f"/p2p/{peer_id}")
    # return Multiaddr(f"/ip4/{ip}/webrtc/p2p/{peer_id}")


def verify_certhash(remote_cert: x509.Certificate, expected_hash: str) -> bool:
    """Verify remote certificate hash matches expected"""
    der_bytes = remote_cert.public_bytes(serialization.Encoding.DER)
    conv_hash = base64.urlsafe_b64encode(hashlib.sha256(der_bytes).digest())
    actual_hash = f"uEi{conv_hash.decode('utf-8').rstrip('=')}"
    return actual_hash == expected_hash


def create_webrtc_direct_multiaddr(ip: str, port: int, peer_id: ID) -> Multiaddr:
    """Create a WebRTC-direct multiaddr"""
    # Format: /ip4/<ip>/udp/<port>/webrtc-direct/p2p/<peer_id>
    return Multiaddr(f"/ip4/{ip}/udp/{port}/webrtc-direct/p2p/{peer_id}")


def parse_webrtc_maddr(maddr: Multiaddr) -> tuple[str, ID, str]:
    """
    Parse a WebRTC multiaddr like:
    /ip4/147.28.186.157/udp/9095/webrtc-direct/certhash/uEiDFVmAomKdAbivdrcIKdXGyuij_ax8b8at0GY_MJXMlwg/p2p/12D3KooWFhXabKDwALpzqMbto94sB7rvmZ6M28hs9Y9xSopDKwQr/p2p-circuit
    /ip6/2604:1380:4642:6600::3/tcp/9095/p2p/12D3KooWFhXabKDwALpzqMbto94sB7rvmZ6M28hs9Y9xSopDKwQr/p2p-circuit/webrtc
    /ip4/147.28.186.157/udp/9095/webrtc-direct/certhash/uEiDFVmAomKdAbivdrcIKdXGyuij_ax8b8at0GY_MJXMlwg/p2p/12D3KooWFhXabKDwALpzqMbto94sB7rvmZ6M28hs9Y9xSopDKwQr/p2p-circuit/webrtc
    /ip4/127.0.0.1/udp/9000/webrtc-direct/certhash/uEia...1jI/p2p/12D3KooW...6HEh
    Returns (ip, peer_id, certhash)
    """
    try:
        if isinstance(maddr, str):
            maddr = Multiaddr(maddr)

        parts = maddr.to_string().split("/")

        # Get IP (after ip4 or ip6)
        ip_idx = parts.index("ip4" if "ip4" in parts else "ip6") + 1
        ip = parts[ip_idx]

        # Get certhash (after certhash)
        certhash_idx = parts.index("certhash") + 1
        certhash = parts[certhash_idx]

        # Get peer ID (after p2p)
        peer_id_idx = parts.index("p2p") + 1
        peer_id = parts[peer_id_idx]

        if not all([ip, peer_id, certhash]):
            raise ValueError("Missing required components in multiaddr")

        return ip, peer_id, certhash

    except Exception as e:
        raise ValueError(f"Invalid WebRTC ma: {e}")


def generate_local_certhash(cert_pem: bytes) -> bytes:
    cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
    der_bytes = cert.public_bytes(encoding=serialization.Encoding.DER)
    digest = hashlib.sha256(der_bytes).digest()
    certhash = base58.b58encode(digest).decode()
    print(f"local_certhash= {certhash}")
    return f"uEi{certhash}"  # js-libp2p compatible


def generate_webrtc_multiaddr(
    ip: str, peer_id: str, certhash: Optional[str] = None
) -> Multiaddr:
    if not certhash:
        raise ValueError("certhash must be provided for /webrtc-direct multiaddr")

    cert_mgr = CertificateManager()
    certhash = cert_mgr.get_certhash() if not certhash else certhash
    if not isinstance(peer_id, ID):
        peer_id = ID(peer_id)

    base = f"/ip4/{ip}/udp/9000/webrtc-direct/certhash/{certhash}/p2p/{peer_id}"

    return Multiaddr(base)


def filter_addresses(addrs: list[Multiaddr]) -> list[Multiaddr]:
    """
    Filters the given list of multiaddresses,
    returning only those that are valid for WebRTC transport.

    A valid WebRTC multiaddress typically contains /webrtc/ or /webrtc-direct/.
    """
    valid_protocols = {"webrtc", "webrtc-direct"}

    def is_valid_webrtc_addr(addr: Multiaddr) -> bool:
        try:
            protocols = [proto.name for proto in addr.protocols()]
            return any(p in valid_protocols for p in protocols)
        except Exception:
            return False

    return [addr for addr in addrs if is_valid_webrtc_addr(addr)]
