"""
OpenSSL helpers for libp2p TLS.

Python's ssl module maps CERT_OPTIONAL to OpenSSL peer verification, which
rejects self-signed libp2p identity certificates with TLSV1_ALERT_UNKNOWN_CA
before our libp2p extension verification runs.

Go uses InsecureSkipVerify + VerifyPeerCertificate; Node.js uses
rejectUnauthorized=false + requestCert=true + custom verifyPeerCertificate.
We mirror that by requesting peer certificates while skipping PKIX verification
at the OpenSSL layer via a verify callback that always accepts.

See libp2p specs/tls/tls.md Peer Authentication: identity is carried in a
self-signed certificate with the libp2p Public Key Extension, not PKIX CA trust.

Platform requirements
---------------------
- **CPython only.** ``_ssl_ctx_ptr()`` reads the undocumented ``PySSLContext``
  struct layout via ``id(context) + offset``. This is unsupported on PyPy,
  GraalPython, and other non-CPython runtimes.
- **libssl coupling.** ctypes must load the same OpenSSL shared library that
  CPython's ``_ssl`` module is linked against. On Windows we prefer the DLL
  directory adjacent to ``_ssl.pyd``; on Unix we use ``find_library("ssl")``.

Long-term, an upstream CPython API exposing the ``SSL_CTX*`` handle would
remove the need for the layout hack.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from pathlib import Path
import ssl
import sys
from typing import Any

# OpenSSL SSL_VERIFY_PEER requests a peer certificate during the handshake.
_VERIFY_PEER = 0x01

_libssl: ctypes.CDLL | None = None
_SSL_CTX_set_verify: Any = None


def _load_libssl() -> ctypes.CDLL:
    """Load the platform OpenSSL libssl shared library."""
    if sys.platform == "win32":
        import _ssl

        dll_file = getattr(_ssl, "__file__", None)
        if dll_file:
            dll_dir = Path(dll_file).resolve().parent
            for name in ("libssl-3.dll", "libssl-1_1.dll", "ssleay32.dll"):
                for candidate in (dll_dir / name, Path(name)):
                    if not candidate.is_file():
                        continue
                    try:
                        return ctypes.CDLL(str(candidate))
                    except OSError:
                        continue
        raise RuntimeError("Could not load libssl on Windows")

    if sys.platform == "darwin":
        # On macOS, Apple ships system LibreSSL in /usr/lib which causes ABI collisions
        # with CPython's OpenSSL 3. Search Homebrew and MacPorts OpenSSL 3 first.
        darwin_candidates = (
            "/opt/homebrew/opt/openssl@3/lib/libssl.3.dylib",
            "/opt/homebrew/opt/openssl@3/lib/libssl.dylib",
            "/usr/local/opt/openssl@3/lib/libssl.3.dylib",
            "/usr/local/opt/openssl@3/lib/libssl.dylib",
            "/opt/homebrew/lib/libssl.3.dylib",
            "/usr/local/lib/libssl.3.dylib",
            "/opt/local/lib/openssl3/libssl.3.dylib",
            "/opt/local/lib/libssl.3.dylib",
        )
        for candidate in darwin_candidates:
            if Path(candidate).is_file():
                try:
                    return ctypes.CDLL(candidate)
                except OSError:
                    continue

    for fallback in (
        "libssl.so.3",
        "libssl.so.1.1",
        "libssl.3.dylib",
        "libssl.dylib",
        "ssl",
    ):
        try:
            return ctypes.CDLL(fallback)
        except OSError:
            pass

    libname = ctypes.util.find_library("ssl")
    if libname is not None:
        try:
            return ctypes.CDLL(libname)
        except OSError:
            pass

    raise RuntimeError("Could not load libssl")


def _ensure_libssl() -> None:
    global _libssl, _SSL_CTX_set_verify
    if _libssl is not None:
        return
    _libssl = _load_libssl()
    _SSL_CTX_set_verify = _libssl.SSL_CTX_set_verify
    _SSL_CTX_set_verify.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    _SSL_CTX_set_verify.restype = None


def _ssl_ctx_ptr(context: ssl.SSLContext) -> int:
    """
    Return the OpenSSL SSL_CTX* for a Python SSLContext (CPython layout).

    Reads ``PySSLContext.ctx`` via a fixed offset past ``PyObject_HEAD``
    (16 bytes on 64-bit, 8 bytes on 32-bit). This layout is undocumented and
    may change in future CPython versions or free-threaded builds.
    """
    offset = 16 if sys.maxsize > 2**32 else 8
    # pyrefly: ignore
    ptr = ctypes.cast(
        id(context) + offset,
        ctypes.POINTER(ctypes.c_void_p),
    ).contents.value
    if ptr is None:
        raise RuntimeError("failed to resolve SSL_CTX pointer from SSLContext")
    return ptr


def _accept_all_verify_cb(_preverify_ok: int, _x509_ctx: int) -> int:
    return 1


_VerifyCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p)

# Single process-lifetime callback; OpenSSL stores only a pointer.
_ACCEPT_ALL_VERIFY_CB = _VerifyCallback(_accept_all_verify_cb)


def install_skip_pkix_peer_verification(context: ssl.SSLContext) -> None:
    """
    Request peer certificates but skip PKIX/CA chain verification.

    libp2p specs/tls/tls.md requires servers to request client authentication
    during the TLS handshake (Handshake Protocol) and endpoints to verify peer
    identity via the libp2p Public Key Extension (Peer Authentication), not via
    PKIX CA chains.  This helper satisfies the TLS-layer certificate request
    while deferring identity checks to verify_certificate_chain().
    """
    if sys.implementation.name != "cpython":
        raise RuntimeError(
            "libp2p TLS PKIX skip requires CPython; "
            f"unsupported implementation: {sys.implementation.name}"
        )
    _ensure_libssl()
    _SSL_CTX_set_verify(_ssl_ctx_ptr(context), _VERIFY_PEER, _ACCEPT_ALL_VERIFY_CB)
