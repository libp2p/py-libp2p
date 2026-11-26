# Migration Notes: Adapting Python Transport Test from Old to New Format

## Overview

This document outlines the changes needed to adapt the Python transport interop test from the old `transport-interop` format to the new `transport` format.

## Key Differences

### 1. Environment Variables

**Old Format:**

- `LIBP2P_DEBUG` (uppercase)

**New Format:**

- `debug` (lowercase)

**Change Required:**

```python
# OLD:
debug_enabled = os.getenv("LIBP2P_DEBUG", "").upper() in ["DEBUG", "1", "TRUE", "YES"]

# NEW:
debug_enabled = os.getenv("debug", "false").upper() in ["DEBUG", "1", "TRUE", "YES"]
```

### 2. Dockerfile Changes

**Old Format (transport-interop):**

- Copies from extracted zip: `COPY py-libp2p-* /app/py-libp2p`
- Copies pyproject.toml from root: `COPY pyproject.toml .`
- Has multihash conflict fix
- Has commented-out yamux patch

**New Format (transport):**

- Copies from current directory: `COPY ./ /app/py-libp2p`
- Copies pyproject.toml from interop/transport: `COPY interop/transport/pyproject.toml .`
- Simpler structure (no zip extraction needed)

**Current Dockerfile is already correct for new format!**

### 3. Missing Features in Current py-libp2p Implementation

The old format has several features that should be ported:

#### A. WSS/TLS Support

- TLS client config for WSS dialing
- TLS server config with self-signed certificates for WSS listening
- Requires `cryptography` library

#### B. Enhanced Error Handling

- More detailed traceback printing
- Better error messages with exception types

#### C. WSS Address Conversion

- Converts `/tls/ws` to `/wss` for compatibility with Go implementations
- Handles WSS dialer workarounds

#### D. Better Logging

- More comprehensive debug output
- Better error context

## Required Changes

### 1. Update `ping_test.py`

#### Change debug environment variable:

```python
# Line 48: Change from LIBP2P_DEBUG to debug
debug_enabled = os.getenv("debug", "false").upper() in ["DEBUG", "1", "TRUE", "YES"]
```

#### Add missing imports for WSS/TLS support:

```python
import ssl
import tempfile
import ipaddress
from typing import Optional
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime, timedelta
```

#### Add TLS configuration methods (from old format):

- `create_tls_client_config()` - for WSS dialing
- `create_tls_server_config()` - for WSS listening with self-signed certs

#### Update `run_listener()` to use TLS config:

```python
# Configure TLS for WSS
tls_client_config = self.create_tls_client_config()
tls_server_config = self.create_tls_server_config()

self.host = new_host(
    key_pair=key_pair,
    sec_opt=sec_opt,
    muxer_opt=muxer_opt,
    listen_addrs=listen_addrs,
    enable_quic=(self.transport == "quic-v1"),
    tls_client_config=tls_client_config,  # ADD THIS
    tls_server_config=tls_server_config    # ADD THIS
)
```

#### Update `run_dialer()` to:

- Handle `/tls/ws` to `/wss` conversion
- Use TLS client config for WSS
- Handle WSS dialer workarounds

#### Fix `run_listener()` duplicate code:

The current implementation has duplicate `listen_addrs` assignment - remove the duplicate.

### 2. Update `pyproject.toml`

Add `cryptography` dependency for TLS support:

```toml
dependencies = [
    "libp2p @ file:///app/py-libp2p",
    "redis>=4.0.0",
    "typing-extensions>=4.0.0",
    "cryptography>=41.0.0",  # ADD THIS for TLS/WSS support
]
```

### 3. Update `Dockerfile`

The current Dockerfile is mostly correct, but ensure:

- It copies from current directory (✓ already correct)
- It installs all dependencies including cryptography (add if missing)

## Summary of Changes Needed

1. ✅ **Dockerfile**: Already correct for new format
1. ❌ **ping_test.py**:
   - Change `LIBP2P_DEBUG` → `debug`
   - Add WSS/TLS support methods
   - Add missing imports
   - Fix duplicate `listen_addrs` in `run_listener()`
   - Add WSS address conversion logic
   - Enhance error handling
1. ❌ **pyproject.toml**: Add `cryptography` dependency

## Testing

After making changes:

1. Commit to py-libp2p repository
1. Update commit SHA in `transport/impls.yaml`
1. Test with: `./run_tests.sh --test-select "python" --force-image-rebuild --yes`
