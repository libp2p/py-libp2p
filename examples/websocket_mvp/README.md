# Enhanced WebSocket Transport Demo with libp2p

A clean, minimal WebSocket example showcasing enhanced transport features using **libp2p WebSocket transport** with Echo and Ping protocols.

## 📁 Files

- `server.py` - Enhanced WebSocket server using libp2p WebSocket transport
- `client.py` - Python client using libp2p WebSocket transport
- `client.html` - Browser client with modern UI (for libp2p multiaddrs)
- `serve_html.py` - HTTP server for serving HTML files
- `README.md` - This file

## 🚀 Quick Start

### 1. Start libp2p WebSocket Server

```bash
cd /home/yks/pldg/ys-lib/examples/websocket_mvp
python server.py
```

The server will print its full multiaddr (e.g., `/ip4/127.0.0.1/tcp/8080/ws/p2p/12D3KooW...`)

### 2. Start HTTP Server (in another terminal)

```bash
cd /home/yks/pldg/ys-lib/examples/websocket_mvp
python serve_html.py
```

### 3. Test with Python Client

```bash
cd /home/yks/pldg/ys-lib/examples/websocket_mvp
python client.py
```

**Note**: Update the `server_addr` variable in `client.py` with the actual server multiaddr.

### 4. Test with Browser Client

- Open: `http://localhost:8000/client.html`
- Enter the server's full multiaddr in the "Server Multiaddr" field
- Click "Connect"
- Test Echo and Ping protocols

## ✨ Features

- **libp2p WebSocket Transport**: Uses the actual libp2p WebSocket implementation
- **Echo Protocol**: Send messages and get them echoed back via libp2p streams
- **Ping Protocol**: Send ping and get pong responses via libp2p streams
- **Secure Connections**: libp2p WebSocket with enhanced transport features
- **Real-time Communication**: Bidirectional message exchange through libp2p
- **Modern UI**: Beautiful browser client with statistics
- **Python Client**: Automated testing of protocols using libp2p

## 🔧 Protocol Details

### Echo Protocol (`/echo/1.0.0`)

- **libp2p Stream**: Opens stream to `/echo/1.0.0` protocol
- **Send**: Message via libp2p stream
- **Receive**: Echoed message via libp2p stream

### Ping Protocol (`/ping/1.0.0`)

- **libp2p Stream**: Opens stream to `/ping/1.0.0` protocol
- **Send**: "ping" via libp2p stream
- **Receive**: "pong" via libp2p stream

## 🎯 What This Demonstrates

- **libp2p WebSocket Transport**: Real libp2p WebSocket implementation
- **Protocol-based Stream Handling**: libp2p stream multiplexing
- **Real-time Communication**: Bidirectional libp2p streams
- **Secure Connection Management**: libp2p security and transport layers
- **Browser Integration**: Modern UI for libp2p multiaddrs
- **Python Client Automation**: libp2p client testing

This demonstrates the **actual libp2p WebSocket transport** capabilities with Echo and Ping protocols, showcasing the enhanced transport features in `ys-lib`!
