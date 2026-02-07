# eth-off-chain-discovery

Decentralized off-chain service discovery using Ethereum smart contracts and libp2p Kademlia DHT.

## Overview

This example demonstrates a hybrid discovery system:
1. **On-chain registry**: Ethereum smart contract stores service ownership and DHT pointers.
2. **Off-chain resolution**: libp2p Kademlia DHT stores signed, verifiable peer records.


<img src="./images/sequence_diagram.png" alt="Workflow">

## Prerequisites

- Python 3.10+
- Foundry (forge) for Solidity
- Ethereum testnet RPC (e.g., Sepolia via Infura/Alchemy)
- Testnet ETH for gas

## Quick Start

### 1. Clone and Setup

```bash
cd py-libp2p/product-innovation/eth-libp2p-discovery

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set Python path
export PYTHONPATH=.
```

### 2. Configure Environment

Create `.env` file:

```bash
RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
PRIVATE_KEY=0x...your_private_key...
SERVICE_ID_STR=service1, service2, service3
LISTEN_ADDRS=your-listening-addresses
```

| Variable | Description |
|----------|-------------|
| `RPC_URL` | Ethereum RPC endpoint |
| `PRIVATE_KEY` | Wallet private key |
| `SERVICE_ID_STR` | Unique service identifier  |
| `LISTEN_ADDRS` | libp2p listen addresses, comma-separated |

### 3. Deploy Smart Contract

```bash
cd contracts
forge script script/Deploy.s.sol --rpc-url $RPC_URL --broadcast --private-key $PRIVATE_KEY
```

> Note: Add `--verify` flag to verify contract on-chain.

A `deploy_output.json` file is created with deployed contract info:

```json
{
  "contract_address": "0x...",
  "abi": {
    "abi": [...]
  }
}
```

### 4. Run Publisher

```bash
3 scripts/publish_service.py
```

The publisher will:
- Deterministically derive Ed25519 keys from your ETH private key.
- Register service on-chain (if not already registered).
- Set DHT base pointer on-chain.
- Publish a signed peer record to `/service/{hash}/{peer_id}`.
- Announce as a provider for `/service/{hash}`.

A `keys/` directory is updated with:
- `{service}_pubkey.hex`: Public key (shared with resolvers for verification).
- `{service}_publisher_addr.txt`: Bootstrap address with PeerID.

### 5. Run Resolver (separate terminal)

```bash
python3 scripts/resolve_service.py
```

The resolver will:
- Read the on-chain pointer to get the DHT base key.
- Connect to the publisher node using the bootstrap address.
- Use `find_providers` to discover all nodes providing the service.
- Fetch and verify individual signed records for each provider.
- Exit automatically once all results are displayed.

## Project Structure

```
eth-libp2p-discovery/
├── scripts/
│   ├── publish_service.py    # Publisher script
│   └── resolve_service.py    # Resolver script
├── p2p/
│   ├── constants.py          # Configuration and constants
│   ├── logging_config.py     # Logging
│   ├── node.py               # Libp2p node wrapper
│   ├── dht.py                # DHT utilities
│   ├── record.py             # Service record signing/verification
│   ├── validator.py          # DHT namespace validator
│   ├── service_publisher.py  # Publishing logic
│   └── service_resolver.py   # Resolution logic
├── contracts/                 # Solidity smart contracts       
└── requirements.txt           # Python dependencies
```

## Multi-Provider Discovery

The system supports multiple nodes providing the same service:
1.  **Unique Keys**: Each provider stores its record at `/service/{id_hash}/{peer_id}`.
2.  **Providers**: Publishers announce themselves via `dht.provide(id_hash)`.
3.  **Discovery**: Resolvers use `dht.find_providers(id_hash)` to find all service nodes.
4.  **One-Shot**: Resolvers discover all providers, verify their records, and exit.

## License

MIT
