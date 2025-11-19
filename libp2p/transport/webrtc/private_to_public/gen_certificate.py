import base64
import datetime
import hashlib
import logging
from typing import cast

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
    ec,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from cryptography.x509.oid import (
    NameOID,
)
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.peer.id import (
    ID,
)

from ..constants import (
    DEFAULT_CERTIFICATE_LIFESPAN,
    DEFAULT_CERTIFICATE_RENEWAL_THRESHOLD,
)

SIGNAL_PROTOCOL = "/libp2p/webrtc/signal/1.0.0"
logger = logging.getLogger("libp2p.transport.webrtc.certificate")


# TODO: Once Datastore is implemented in python, add cert and priv_key storage
#       and management.
class WebRTCCertificate:
    """WebRTC certificate for connections"""

    def __init__(
        self,
        cert: x509.Certificate | None = None,
        private_key: ec.EllipticCurvePrivateKey | None = None,
    ) -> None:
        # Initialize all attributes first
        self.private_key = None
        self.cert = None
        self._fingerprint: str | None = None
        self._certhash: str | None = None

        if private_key is None:
            self.private_key = self.loadOrCreatePrivateKey(True)
        else:
            self.private_key = private_key

        if self.private_key is None:
            raise Exception("Failed to load or create private key")

        if cert is None:
            self.cert, _, _ = self.loadOrCreateCertificate(self.private_key)
        else:
            self.cert = cert

        if self.cert is None:
            raise Exception("Failed to load or create certificate")

        self.cancel_scope: trio.CancelScope | None = None

    @property
    def fingerprint(self) -> str:
        """Get SHA-256 fingerprint of certificate"""
        if self._fingerprint is None:
            assert self.cert is not None, "Certificate must be initialized"
            cert_der = self.cert.public_bytes(Encoding.DER)
            sha256_hash = hashlib.sha256(cert_der).digest()
            self._fingerprint = ":".join(f"{b:02x}" for b in sha256_hash).upper()
        return self._fingerprint

    @property
    def certhash(self) -> str:
        """Get multibase-encoded certificate hash for multiaddr"""
        if self._certhash is None:
            assert self.cert is not None, "Certificate must be initialized"
            cert_der = self.cert.public_bytes(Encoding.DER)
            sha256_hash = hashlib.sha256(cert_der).digest()
            # Multibase base32 encoding with 'u' prefix for base32pad-upper
            # Convert to base64url first, then format as multibase
            b64_hash = base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")
            # Use "uEi" prefix for libp2p WebRTC certificate hash format
            self._certhash = "uEi" + b64_hash
        return self._certhash

    def to_pem(self) -> tuple[bytes, bytes]:
        """Export certificate and private key as PEM"""
        assert self.cert is not None, "Certificate must be initialized"
        cert_pem = self.cert.public_bytes(Encoding.PEM)
        assert self.private_key is not None
        key_pem = self.private_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
        return cert_pem, key_pem

    @staticmethod
    def from_pem(cert_pem: bytes, key_pem: bytes) -> "WebRTCCertificate":
        """Load certificate from PEM data"""
        cert = x509.load_pem_x509_certificate(cert_pem)
        private_key = cast(
            ec.EllipticCurvePrivateKey,
            serialization.load_pem_private_key(key_pem, password=None),
        )

        instance = WebRTCCertificate(cert, private_key)
        return instance

    # TODO: Implement this
    def validate_pem_export(self) -> bool:
        """
        Comprehensive PEM export validation using cryptographic verification.
        """
        # Export to PEM
        # cert_pem, key_pem = self.to_pem()

        # # 1. Round-trip validation (most important)
        # imported_cert = self.from_pem(cert_pem, key_pem)
        # if imported_cert.certhash != self.certhash:
        #     raise ValueError("Round-trip certhash mismatch")
        # if imported_cert.fingerprint != self.fingerprint:
        #     raise ValueError("Round-trip fingerprint mismatch")

        # # 2. Cryptographic validation
        # cert_obj = x509.load_pem_x509_certificate(cert_pem)
        # key_obj = serialization.load_pem_private_key(key_pem, password=None)

        # # Ensure we're working with RSA keys (as required by WebRTCCertificate)
        # if not isinstance(key_obj, CryptoRSAPrivateKey):
        #     raise ValueError("WebRTCCertificate validation requires RSA private key")

        # # 3. Key-certificate matching (RSA-specific validation)
        # cert_public_key = cert_obj.public_key()
        # # Only check public_numbers for RSA keys
        # if isinstance(cert_public_key, rsa.RSAPublicKey) and isinstance(
        #     key_obj.public_key(), rsa.RSAPublicKey
        # ):
        #     if (
        #         cert_public_key.public_numbers()
        #         != key_obj.public_key().public_numbers()
        #     ):
        #         raise ValueError("Certificate and private key don't match")
        # else:
        #     # Fallback: compare public key bytes
        #     cert_public_bytes = cert_public_key.public_bytes(
        #         encoding=serialization.Encoding.DER,
        #         format=serialization.PublicFormat.SubjectPublicKeyInfo,
        #     )
        #     key_public_bytes = key_obj.public_key().public_bytes(
        #         encoding=serialization.Encoding.DER,
        #         format=serialization.PublicFormat.SubjectPublicKeyInfo,
        #     )
        #     if cert_public_bytes != key_public_bytes:
        #         raise ValueError("Certificate and private key don't match")

        # # 4. Certificate properties validation
        # common_name_attr =
        #   cert_obj.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0]
        # common_name = common_name_attr.value
        # # Handle both string and bytes values
        # common_name_str = (
        #     common_name if isinstance(common_name, str) else str(common_name)
        # )
        # if common_name_str != "libp2p-webrtc":
        #     raise ValueError(f"Invalid certificate subject: {common_name_str}")

        # # 5. Key strength validation (RSA-specific)
        # if hasattr(key_obj, "key_size"):
        #     if key_obj.key_size < 2048:
        #         raise ValueError(f"Insufficient key size: {key_obj.key_size}")
        # else:
        #     raise ValueError("Cannot validate key size for non-RSA key")

        # # 6. PEM format validation
        # cert_lines = cert_pem.decode().strip().split("\n")
        # if cert_lines[0] != "-----BEGIN CERTIFICATE-----":
        #     raise ValueError("Invalid certificate PEM header")
        # if cert_lines[-1] != "-----END CERTIFICATE-----":
        #     raise ValueError("Invalid certificate PEM footer")

        # key_lines = key_pem.decode().strip().split("\n")
        # if key_lines[0] != "-----BEGIN PRIVATE KEY-----":
        #     raise ValueError("Invalid private key PEM header")
        # if key_lines[-1] != "-----END PRIVATE KEY-----":
        #     raise ValueError("Invalid private key PEM footer")

        return True

    def _getCertRenewalTime(self) -> int:
        # Return ms until cert expiry minus renewal threshold.
        assert self.cert is not None, "Certificate must be initialized"
        # Use not_valid_after_utc to get timezone-aware datetime
        cert_expiry = self.cert.not_valid_after_utc
        renew_at = cert_expiry - datetime.timedelta(
            milliseconds=DEFAULT_CERTIFICATE_RENEWAL_THRESHOLD
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        renewal_time_ms = int((renew_at - now).total_seconds() * 1000)
        return renewal_time_ms if renewal_time_ms > 0 else 100

    def loadOrCreatePrivateKey(
        self, forceRenew: bool = False
    ) -> ec.EllipticCurvePrivateKey:
        """
        Load the existing private key if available, or generate a new one.

        Args:
            forceRenew (bool): If True, always generate a new private key even if one
                                already exists.
                            If False, return the existing private key if present.

        Returns:
            ec.EllipticCurvePrivateKey:
                The loaded or newly generated elliptic curve private key.

        """
        # If private key is already present and not enforced to create new
        if self.private_key is not None and not forceRenew:
            return self.private_key

        # Create a new private key
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        return self.private_key

    def loadOrCreateCertificate(
        self, private_key: ec.EllipticCurvePrivateKey | None, forceRenew: bool = False
    ) -> tuple[x509.Certificate, bytes, str]:
        """
        Generate or load a self-signed WebRTC certificate for libp2p direct connections.

        If a valid certificate already exists and is not expired, and the public key
        matches, it will be reused unless forceRenew is True.
        Otherwise, a new certificate is generated.

        Args:
            private_key (ec.EllipticCurvePrivateKey | None): The private key to use
                for signing the certificate. If None, uses self.private_key.
            forceRenew (bool): If True, always generate a new certificate even if the
                current one is valid.

        Returns:
            tuple[x509.Certificate, str, str]: The certificate object, its PEM-encoded
                string, and the base64url-encoded SHA-256 hash of the certificate.

        Raises:
            Exception: If no private key is available to issue a certificate.

        """
        if private_key is None:
            if self.private_key is None:
                raise Exception("Can't issue certificate without private key")
            private_key = self.private_key

        if self.cert is not None and not forceRenew:
            # Check if certificate has to be renewed
            isExpired = (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(milliseconds=DEFAULT_CERTIFICATE_RENEWAL_THRESHOLD)
                >= self.cert.not_valid_after_utc
            )
            if not isExpired:
                # Check if the certificate's public key matches with provided key pair
                public_key = cast(ec.EllipticCurvePublicKey, self.cert.public_key())
                cert_pub = public_key.public_numbers()
                priv_pub = private_key.public_key().public_numbers()
                if cert_pub == priv_pub:
                    cert_pem, _ = self.to_pem()
                    cert_hash = self.certhash
                    return (self.cert, cert_pem, cert_hash)

        common_name: str = "libp2p-webrtc"
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),  # type: ignore[arg-type]
            ]
        )

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(milliseconds=DEFAULT_CERTIFICATE_LIFESPAN)
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                    ]
                ),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )
        self.cert = cert
        cert_pem, _ = self.to_pem()
        cert_hash = self.certhash
        return (cert, cert_pem, cert_hash)

    async def renewal_loop(self) -> None:
        """Certificate renewal loop that runs until cancelled."""
        try:
            while True:
                await trio.sleep(float(self._getCertRenewalTime()))
                logger.debug("Renewing TLS certificate")
                self.loadOrCreateCertificate(self.private_key, True)
        except trio.Cancelled:
            logger.debug("Certificate renewal loop cancelled")
            raise


def create_webrtc_multiaddr(
    ip: str, peer_id: ID, certhash: str, direct: bool = False
) -> Multiaddr:
    """Create WebRTC multiaddr with proper format"""
    # For direct connections
    if direct:
        return Multiaddr(
            f"/ip4/{ip}/udp/0/webrtc-direct/certhash/{certhash}/p2p/{peer_id}"
        )

    # For signaled connections
    return Multiaddr(f"/ip4/{ip}/webrtc/certhash/{certhash}/p2p/{peer_id}")
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


def parse_webrtc_maddr(maddr: Multiaddr | str) -> tuple[str, str, str]:
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

        # Use str() instead of to_string() method
        parts = str(maddr).split("/")

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
