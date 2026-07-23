"""WSS self-signed certificate factory.

The certificate is generated once per process and cached.
"""
from __future__ import annotations

import ipaddress
import ssl
import tempfile
import traceback
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

_cached_ctx: ssl.SSLContext | None = None


def get_wss_server_context() -> ssl.SSLContext | None:
    """Return (and cache) an SSLContext with a self-signed cert for WSS tests."""
    global _cached_ctx
    if _cached_ctx is None:
        _cached_ctx = _build_ssl_context()
    return _cached_ctx


def _build_ssl_context() -> ssl.SSLContext | None:
    try:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "libp2p"),
            x509.NameAttribute(NameOID.COMMON_NAME, "libp2p.local"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow())
            .not_valid_after(datetime.utcnow() + timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with (
            tempfile.NamedTemporaryFile(mode="wb", delete=False) as cf,
            tempfile.NamedTemporaryFile(mode="wb", delete=False) as kf,
        ):
            cf.write(cert.public_bytes(serialization.Encoding.PEM))
            kf.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            ctx.load_cert_chain(cf.name, kf.name)
        return ctx
    except Exception:
        traceback.print_exc()
        return None
