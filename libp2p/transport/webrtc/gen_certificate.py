import base64
import datetime
import hashlib
import logging
from typing import (
    Tuple,
    Dict
)

from aiortc import (
    RTCCertificate,
)
import base58
import base64
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
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey as CryptoRSAPrivateKey
) 
from cryptography.hazmat.primitives.asymmetric import (
    rsa,
)
from cryptography.x509.oid import (
    NameOID,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    NoEncryption
)
from multiaddr import (
    Multiaddr,
)

from libp2p.peer.id import (
    ID,
)

SIGNAL_PROTOCOL = "/libp2p/webrtc/signal/1.0.0"
logger = logging.getLogger("libp2p.transport.webrtc.certificate")


class WebRTCCertificate:
    """WebRTC certificate for connections"""
    
    def __init__(self, cert: x509.Certificate, private_key: rsa.RSAPrivateKey) -> None:
        self.cert = cert
        self.private_key = private_key
        self._fingerprint: str | None = None
        self._certhash: str | None = None
    
    @classmethod
    def generate(cls) -> 'WebRTCCertificate':
        """Generate a new self-signed certificate for WebRTC"""
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Create certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "libp2p-webrtc"),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
            ]),
            critical=False,
        ).sign(private_key, hashes.SHA256())
        
        return cls(cert, private_key)
    
    @property
    def fingerprint(self) -> str:
        """Get SHA-256 fingerprint of certificate"""
        if self._fingerprint is None:
            cert_der = self.cert.public_bytes(Encoding.DER)
            sha256_hash = hashlib.sha256(cert_der).digest()
            self._fingerprint = ':'.join(f'{b:02x}' for b in sha256_hash).upper()
        return self._fingerprint
    
    @property
    def certhash(self) -> str:
        """Get multibase-encoded certificate hash for multiaddr"""
        if self._certhash is None:
            cert_der = self.cert.public_bytes(Encoding.DER)
            sha256_hash = hashlib.sha256(cert_der).digest()
            # Multibase base32 encoding with 'u' prefix for base32pad-upper
            # Convert to base64url first, then format as multibase
            b64_hash = base64.urlsafe_b64encode(sha256_hash).decode().rstrip('=')
            # Use "uEi" prefix for libp2p WebRTC certificate hash format
            self._certhash = 'uEi' + b64_hash
        return self._certhash
    
    def to_pem(self) -> Tuple[bytes, bytes]:
        """Export certificate and private key as PEM"""
        cert_pem = self.cert.public_bytes(Encoding.PEM)
        assert self.private_key is not None
        key_pem = self.private_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.PKCS8,
            NoEncryption()
        )
        return cert_pem, key_pem
    
    @classmethod
    def from_pem(cls, cert_pem: bytes, key_pem: bytes) -> 'WebRTCCertificate':
        """Load certificate from PEM data"""
        cert = x509.load_pem_x509_certificate(cert_pem)
        private_key = serialization.load_pem_private_key(key_pem, password=None)
    
        if not isinstance(private_key, CryptoRSAPrivateKey):
            raise TypeError("WebRTCCertificate only supports RSA private keys")
        return cls(cert, private_key)



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


def generate_local_certhash(cert_pem: bytes) -> str:
    cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
    der_bytes = cert.public_bytes(encoding=serialization.Encoding.DER)
    digest = hashlib.sha256(der_bytes).digest()
    certhash = base58.b58encode(digest).decode()
    print(f"local_certhash= {certhash}")
    return f"uEi{certhash}" 


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
