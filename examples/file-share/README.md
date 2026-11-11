# P2P File Sharing Across NATs

A lightweight, persistent file-sharing proof-of-concept built on `py-libp2p`. It allows two peers behind different NATs/routers to connect and exchange files using UPnP and a custom binary stream protocol.

## Hack Value Features

- **NAT Traversal:** Auto-configures UPnP port mapping (`enable_upnp=True`). The UI visually distinguishes between Local and Public IPs to confirm traversal success.
- **Persistence:** Resolves the "reconnecting to peers" requirement by saving known peer Multiaddrs to a local `friends.json` file.
- **Serverless File Exchange:** Uses a custom header-based protocol (`/file-share/1.0.0`) to transfer filenames and exact file sizes reliably without loading the entire file into RAM.

## Usage

### 1. Start the Receiver

```bash
python share.py -p 8001
```

Wait a moment for the node to detect its Public IP. Copy the Public Multiaddr.

### 2. Start the Sender

```bash
python share.py -p 8002
```

- **Step A:** Select Option 2 (Add Friend). Name them "Receiver" and paste the Multiaddr.
- **Step B:** Select Option 1 (Send File). Type "Receiver" and provide the path to a local file.

The file will stream directly to the receiver's disk with a progress indicator.
