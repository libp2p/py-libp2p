# TLS Security — OpenSSL Loading & CI Type-Check Issues

## Summary

The TLS security module (`libp2p/security/tls/openssl_verify.py`) fails to load the correct `libssl` on macOS (breaking certificate verification) and has pyrefly type-narrowing errors that block CI.

## Issues

- **Wrong libssl loaded on macOS**: The module does not load the exact `libssl` linked by CPython, so certificate verification uses the wrong OpenSSL version.
- **Type-narrowing errors block CI**: `spec.origin` / `ssl_ext_path` / `getattr` results are not narrowed correctly for pyrefly.
- **Temporary `_linked_libssl_path` helper**: A workaround function causes pyrefly errors in CI.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
