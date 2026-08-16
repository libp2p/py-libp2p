# Python Implementation for Transport Test Framework

## Summary

This document describes the Python libp2p v0.x implementation for the transport test framework. The implementation follows the transport test framework specification with proper Redis coordination protocol, correct environment variable handling, standalone transport support, and YAML-formatted output.

## Implementation Details

### 1. Redis Coordination Protocol

**Implementation**: Uses `RPUSH`/`BLPOP` (Redis list operations) as specified in the transport test framework, matching Rust and JavaScript implementations.

**Listener** (`run_listener` method):

- Uses `DEL` operation before `RPUSH` to prevent `WRONGTYPE` errors from stale data
- Uses `RPUSH` to publish listener multiaddr as a list element
- Key format: `{TEST_KEY}_listener_multiaddr`

**Dialer** (`run_dialer` method):

- Uses `BLPOP` (blocking list pop) to wait for listener address
- Properly handles BLPOP return value `(key, value)` tuple format
- Includes timeout handling with proper conversion for Redis commands

**Current Implementation**:

```python
# Listener: Publish address
redis_key = f"{self.test_key}_listener_multiaddr"

# Clean up any existing key to ensure it's a list type
try:
    self.redis_client.delete(redis_key)
except Exception:
    pass  # Ignore if key doesn't exist

# Publish listener address using RPUSH (list operation)
# Dialer will use BLPOP to block and read this value
self.redis_client.rpush(redis_key, actual_addr)

# Dialer: Wait for address
blpop_result = self.redis_client.blpop(
    redis_key, timeout=remaining_timeout
)
if blpop_result:
    # BLPOP returns (key, value) tuple - extract the multiaddr string
    listener_addr = (
        blpop_result[1]
        if isinstance(blpop_result, (list, tuple))
        and len(blpop_result) > 1
        else blpop_result
    )
```

**Files**:

- `transport/images/python/v0.x/py-libp2p/interop/transport/ping_test.py` (lines 737-755, 902-930)

### 2. Environment Variable Handling

**Implementation**: All environment variables use uppercase names only, matching the test framework specification. Variables are strictly required (throw errors if not set) or optional with defaults.

**Current Implementation**:

```python
# Required variables (throw error if not set)
self.transport = os.getenv("TRANSPORT")
if not self.transport:
    raise ValueError("TRANSPORT environment variable is required")

self.redis_addr = os.getenv("REDIS_ADDR")
if not self.redis_addr:
    raise ValueError("REDIS_ADDR environment variable is required")

self.ip = os.getenv("LISTENER_IP")
if not self.ip:
    raise ValueError("LISTENER_IP environment variable is required")

self.test_key = os.getenv("TEST_KEY")
if not self.test_key:
    raise ValueError("TEST_KEY environment variable is required")

is_dialer_value = os.getenv("IS_DIALER")
if is_dialer_value is None:
    raise ValueError("IS_DIALER environment variable is required")
self.is_dialer = is_dialer_value == "true"  # Case-sensitive match

# Optional variables with defaults
debug_value = os.getenv("DEBUG") or "false"  # Optional, default to "false"

timeout_value = os.getenv("TEST_TIMEOUT_SECS") or "180"
raw_timeout = int(timeout_value)
self.test_timeout_seconds = min(raw_timeout, MAX_TEST_TIMEOUT)
```

**Files**:

- `transport/images/python/v0.x/py-libp2p/interop/transport/ping_test.py` (lines 54-64, 94-150)

### 3. Standalone Transport Support

**Implementation**: Properly handles standalone transports (quic-v1) where `SECURE_CHANNEL` and `MUXER` environment variables are optional (not set by the test framework).

**Environment Variable Handling**:

```python
# Standalone transports don't use separate security/muxer
standalone_transports = ["quic-v1"]  # Python currently only supports quic-v1

# Check if transport is standalone before requiring MUXER/SECURE_CHANNEL
if self.transport not in standalone_transports:
    # Non-standalone transports: MUXER and SECURE_CHANNEL are required
    muxer_env = os.getenv("MUXER")
    if muxer_env is None:
        raise ValueError("MUXER environment variable is required")
    self.muxer = muxer_env

    security_env = os.getenv("SECURE_CHANNEL")
    if security_env is None:
        raise ValueError("SECURE_CHANNEL environment variable is required")
    self.security = security_env
else:
    # Standalone transports: MUXER and SECURE_CHANNEL are optional
    muxer_env = os.getenv("MUXER")
    self.muxer = muxer_env if muxer_env else None

    security_env = os.getenv("SECURE_CHANNEL")
    self.security = security_env if security_env else None
```

**Security Options for Standalone Transports**:

```python
def create_security_options(self):
    """Create security options based on configuration."""
    # Standalone transports have security built-in, no separate security needed
    standalone_transports = ["quic-v1"]
    if self.transport in standalone_transports:
        # For standalone transports, return empty security options
        # The security is handled by the transport itself
        key_pair = create_new_key_pair()
        return {}, key_pair

    # Non-standalone transports: create security options as before
    key_pair = create_new_key_pair()

    if self.security == "noise":
        # ... noise setup ...
    elif self.security == "tls":
        # ... tls setup ...
    elif self.security == "plaintext":
        # ... plaintext setup ...
    else:
        raise ValueError(f"Unsupported security: {self.security}")
```

**Muxer Options for Standalone Transports**:

```python
def create_muxer_options(self):
    """Create muxer options based on configuration."""
    # Standalone transports have muxing built-in, no separate muxer needed
    standalone_transports = ["quic-v1"]
    if self.transport in standalone_transports:
        # For standalone transports, return None (no separate muxer)
        # The muxing is handled by the transport itself
        return None

    # Non-standalone transports: create muxer options as before
    if self.muxer == "yamux":
        return create_yamux_muxer_option()
    elif self.muxer == "mplex":
        return create_mplex_muxer_option()
    else:
        raise ValueError(f"Unsupported muxer: {self.muxer}")
```

**Files**:

- `transport/images/python/v0.x/py-libp2p/interop/transport/ping_test.py` (lines 98-119, 183-218)

### 4. Output Format

**Implementation**: Outputs YAML format to stdout as required by the transport test framework:

```python
print("latency:", file=sys.stdout)
print(f"  handshake_plus_one_rtt: {handshake_plus_one_rtt}", file=sys.stdout)
print(f"  ping_rtt: {ping_rtt}", file=sys.stdout)
print("  unit: ms", file=sys.stdout)
```

**Files**:

- `transport/images/python/v0.x/py-libp2p/interop/transport/ping_test.py` (lines 1080-1086)

### 5. TEST_KEY Support

**Implementation**: Uses `TEST_KEY` environment variable for Redis key namespacing with strict validation:

```python
self.test_key = os.getenv("TEST_KEY")
if not self.test_key:
    raise ValueError("TEST_KEY environment variable is required")

redis_key = f"{self.test_key}_listener_multiaddr"
```

**Files**:

- `transport/images/python/v0.x/py-libp2p/interop/transport/ping_test.py` (lines 147-150, 745, 906)

### 6. Code Quality and Error Handling

**Implementation**:

- Type hints: Uses Python type hints (`redis.Redis | None`, `INetStream`)
- Error handling: Comprehensive error handling with descriptive messages
- Redis connection: Retry mechanism with exponential backoff for Redis connections
- Stream creation: Retry mechanism for stream creation to handle timing issues
- Debug logging: Optional debug logging controlled by `DEBUG` environment variable
- Validation: Configuration validation for transports, security, and muxers

**Files**:

- `transport/images/python/v0.x/py-libp2p/interop/transport/ping_test.py` (throughout)

## Testing

The Python v0.x implementation follows the transport test framework specification and is tested as part of the full test suite.

## Compatibility

- ✅ Follows transport test framework specification (`transport/README.md`)
- ✅ Matches Redis protocol used by Rust and JavaScript implementations
- ✅ Uses uppercase environment variables only (as set by test framework)
- ✅ Consistent with JavaScript v3.x reference implementation
- ✅ Supports standalone transports (quic-v1) with proper handling

## Supported Transports

- **Standard transports**: `tcp`, `ws`, `wss`
- **Standalone transports**: `quic-v1` (with built-in security and muxing)

## Supported Security Channels

- **Noise**: Noise protocol for encryption
- **TLS**: TLS protocol for encryption
- **Plaintext**: Insecure transport (for testing)

## Supported Muxers

- **Yamux**: Yamux stream multiplexer
- **Mplex**: Mplex stream multiplexer
