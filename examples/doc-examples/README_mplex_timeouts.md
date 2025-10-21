# Mplex Stream Timeout and Deadline Example

This example demonstrates the new timeout and deadline features in MplexStream, including deadline validation, timeout handling, and real-world timeout scenarios.

## Features Demonstrated

### 🔍 Deadline Validation

- **Negative TTL values**: Returns `False` and doesn't modify deadlines
- **Zero TTL values**: Returns `True` and sets immediate timeout
- **Positive TTL values**: Returns `True` and sets timeout as expected

### ⏰ Timeout Scenarios

- **Normal operation**: Read/write with reasonable timeouts
- **Short timeouts**: Demonstrates timeout behavior with very short deadlines
- **Write timeouts**: Shows timeout handling for write operations
- **Error handling**: Graceful handling of timeout exceptions

### 🛠️ New Methods Demonstrated

- `set_deadline(ttl)`: Sets both read and write deadlines
- `set_read_deadline(ttl)`: Sets read deadline only
- `set_write_deadline(ttl)`: Sets write deadline only
- All methods now return `True`/`False` based on TTL validation

## Usage

The example requires a `--role` parameter to specify whether to run as server or client.

**Note**: Running without parameters will show the help message with all available options.

### 1. Start the Server

```bash
python example_mplex_timeouts.py --role server --port 8000
```

### 2. Start the Client

```bash
python example_mplex_timeouts.py --role client --destination /ip4/127.0.0.1/tcp/8000/p2p/QmServerPeerID
```

### 3. Run with Verbose Logging

```bash
python example_mplex_timeouts.py --role server --port 8000 --verbose
```

## What You'll See

The demo will show:

- ✅ Deadline validation results for different TTL values
- ⏰ Timeout behavior with various deadline settings
- 📤📥 Stream communication with timeout handling
- 🔍 Error handling for invalid TTL values
- 📊 Real-time demonstration of timeout features

## Key Improvements

This example showcases the refactored MplexStream implementation with:

- **Input validation**: Proper handling of negative TTL values
- **Meaningful return values**: Methods return `True`/`False` based on success
- **Unified timeout handling**: Consistent timeout behavior across read/write operations
- **Better error messages**: Descriptive timeout error messages
- **Comprehensive testing**: Edge cases and real-world scenarios

## Technical Details

The example uses:

- **Explicit mplex configuration**: `muxer_opt={MPLEX_PROTOCOL_ID: Mplex}`
- **InsecureTransport**: Plaintext communication for demonstration purposes (not recommended for production)
- **Trio async framework**: Non-blocking timeout operations
- **Comprehensive logging**: Detailed output for understanding timeout behavior

This demonstrates how the new timeout features make MplexStream more robust and easier to use in production applications.
