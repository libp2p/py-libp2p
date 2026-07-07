"""
OpenSSL helpers for libp2p TLS.

Python's ssl module maps CERT_OPTIONAL to OpenSSL peer verification, which
rejects self-signed libp2p identity certificates with TLSV1_ALERT_UNKNOWN_CA
before our libp2p extension verification runs.

Go uses InsecureSkipVerify + VerifyPeerCertificate; Node.js uses
rejectUnauthorized=false + requestCert=true + custom verifyPeerCertificate.
We mirror that by requesting peer certificates while skipping PKIX verification
at the OpenSSL layer via a verify callback that always accepts.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import ssl
from typing import Any

_libssl = ctypes.CDLL(ctypes.util.find_library("ssl"))
SSL_CTX_set_verify = _libssl.SSL_CTX_set_verify
SSL_CTX_set_verify.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
SSL_CTX_set_verify.restype = None

# OpenSSL SSL_VERIFY_PEER requests a peer certificate during the handshake.
_VERIFY_PEER = 0x01

# Keep callbacks alive for the process lifetime; OpenSSL stores only a pointer.
_verify_callbacks: list[Any] = []


def _ssl_ctx_ptr(context: ssl.SSLContext) -> int:
    """Return the OpenSSL SSL_CTX* for a Python SSLContext (CPython layout)."""
    # PySSLContext: PyObject_HEAD (16 bytes on 64-bit) then SSL_CTX *ctx.
    # pyrefly: ignore
    ptr = ctypes.cast(
        id(context) + 16,
        ctypes.POINTER(ctypes.c_void_p),
    ).contents.value
    if ptr is None:
        raise RuntimeError("failed to resolve SSL_CTX pointer from SSLContext")
    return ptr


def _accept_all_verify_cb(_preverify_ok: int, _x509_ctx: int) -> int:
    return 1


_VerifyCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p)


def install_skip_pkix_peer_verification(context: ssl.SSLContext) -> None:
    """
    Request peer certificates but skip PKIX/CA chain verification.

    libp2p verifies peer identity via the libp2p X.509 extension after the
    handshake completes. This must be called after the final verify_mode is set
    on the context.
    """
    verify_cb = _VerifyCallback(_accept_all_verify_cb)
    _verify_callbacks.append(verify_cb)
    SSL_CTX_set_verify(_ssl_ctx_ptr(context), _VERIFY_PEER, verify_cb)
