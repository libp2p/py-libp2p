# Hole Punching Interoperability Tests

Tests for hole punching interoperability between py-libp2p and go-libp2p.

## Prerequisites

- **Go**: 1.21 or later
- **Python**: 3.10+ with py-libp2p installed
- **Virtual environment**: Activated venv in project root

## Running the Tests

```bash
# From the hole_punching directory
cd tests/interop/go_libp2p/hole_punching

# Make script executable (Linux/WSL)
chmod +x test_local.sh

# Convert line endings if needed (WSL)
dos2unix test_local.sh

# Run the test
./test_local.sh
```

## What the Tests Validate

1. **Relay connectivity**: Go relay server accepts connections from both peers
2. **Circuit relay**: Python client connects to Go server through the relay
3. **Stream handling**: Test stream opened and messages exchanged between peers

## Test Components

| Component                      | Description                            |
| ------------------------------ | -------------------------------------- |
| `go_node/relay-server`         | Go-based relay server                  |
| `go_node/hole-punch-server`    | Go server that connects to relay       |
| `py_node/hole_punch_client.py` | Python client connecting through relay |

## Logs

Test logs are written to the `logs/` directory:

- `relay.log` - Relay server output
- `go_server.log` - Go hole punch server output
- `py_client.log` - Python client output
