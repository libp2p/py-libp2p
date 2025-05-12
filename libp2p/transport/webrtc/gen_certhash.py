import base58
import hashlib
import ssl
from typing import (
    Optional,
    List,
    Tuple,
)
from cryptography import x509
from cryptography.hazmat.backends import default_backend
import hashlib
import base64
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import datetime
from multiaddr import Multiaddr
from typing import Tuple
from aiortc import RTCCertificate
from multiaddr.protocols import (
    Protocol,
    add_protocol,
)

SIGNAL_PROTOCOL = "/libp2p/webrtc/signal/1.0.0"

class CertificateManager(RTCCertificate):
    def __init__(self):
        self.private_key = None
        self.certificate = None
        self.certhash = None

    def generate_self_signed_cert(self, common_name: str = "py-libp2p") -> None:
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name)
        ])
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
        return self.certhash

    def get_certificate_pem(self) -> bytes:
        return self.certificate.public_bytes(serialization.Encoding.PEM)

    def get_private_key_pem(self) -> bytes:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )


def parse_webrtc_maddr(maddr: Multiaddr) -> Tuple[str, int, str]:
    """
    Parse a WebRTC multiaddr like:
    /ip4/127.0.0.1/udp/5000/webrtc/certhash/<hash>/p2p/<peer-id>
    Returns (ip, port, certhash)
    """
    addr = Multiaddr(maddr)
    ip = None
    port = None
    certhash = None

    for c in addr.protocols():
        if c.name == "ip4" or c.name == "ip6":
            ip = addr.value_for_protocol(c.name)
        elif c.name == "udp":
            port = int(addr.value_for_protocol("udp"))
        elif c.name == "certhash":
            certhash = addr.value_for_protocol("certhash")

    if not ip or not port or not certhash:
        raise ValueError("Invalid WebRTC multiaddress")

    return ip, port, certhash


def generate_local_certhash(cert_pem: str) -> str:
    cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
    der_bytes = cert.public_bytes(encoding=ssl.Encoding.DER)
    digest = hashlib.sha256(der_bytes).digest()
    certhash = base58.b58encode(digest).decode()
    return f"uEi{certhash}"  # js-libp2p compatible


def generate_webrtc_multiaddr(
    ip: str, peer_id: str, certhash: Optional[str] = None
) -> Multiaddr:
    add_protocol(Protocol(291, "webrtc-direct", "webrtc-direct"))
    add_protocol(Protocol(292, "certhash", "certhash"))
    # certhash = generate_local_certhash()
    if not certhash:
        raise ValueError("certhash must be provided for /webrtc-direct multiaddr")
    
    certificate= RTCCertificate.generateCertificate()
    base = f"/ip4/{ip}/udp/9000/webrtc-direct/certhash/{certhash}/p2p/{peer_id}"
  
    return Multiaddr(base)


def filter_addresses(addrs: List[Multiaddr]) -> List[Multiaddr]:
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
