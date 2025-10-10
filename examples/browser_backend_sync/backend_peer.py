"""
Backend Peer for Browser-to-Backend P2P Sync

This module implements a libp2p host that acts as a backend peer for browser clients.
It provides NAT traversal, peer discovery, and real-time synchronization capabilities.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from typing import Dict, List, Optional, Set
import uuid

import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.abc import INetStream, INotifee
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.peerstore import PeerStore
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.transport import WebsocketTransport
from libp2p.utils.address_validation import get_available_interfaces

from sync_protocol import SyncProtocol, OperationType, SyncOperation

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Protocol IDs
SYNC_PROTOCOL_ID = TProtocol("/sync/1.0.0")
WEBSOCKET_PROTOCOL_ID = TProtocol("/websocket/1.0.0")


class BackendPeer:
    """
    Backend peer that manages browser client connections and synchronization.
    
    Features:
    - WebSocket transport for browser compatibility
    - NAT traversal with mDNS and bootstrap discovery
    - Real-time sync protocol handling
    - Peer connection management
    - Operation conflict resolution
    """

    def __init__(self, port: int = 8000, enable_mdns: bool = True, debug: bool = False):
        self.port = port
        self.enable_mdns = enable_mdns
        self.debug = debug
        self.client_id = f"backend_{uuid.uuid4().hex[:8]}"
        
        # Sync protocol instance
        self.sync_protocol = SyncProtocol(self.client_id)
        
        # Connected clients
        self.connected_clients: Dict[str, Dict] = {}
        self.client_streams: Dict[str, INetStream] = {}
        
        # WebSocket server for browser clients
        self.websocket_server = None
        self.websocket_clients: Set = set()
        
        # Host and network components
        self.host: Optional[BasicHost] = None
        self.running = False
        
        # Statistics
        self.stats = {
            "operations_processed": 0,
            "clients_connected": 0,
            "start_time": time.time()
        }

    def create_host(self) -> BasicHost:
        """Create and configure the libp2p host."""
        # Create key pair
        key_pair = create_new_key_pair()
        peer_id = ID.from_pubkey(key_pair.public_key)
        peer_store = PeerStore()
        peer_store.add_key_pair(peer_id, key_pair)

        # Create Noise transport for security
        noise_transport = NoiseTransport(
            libp2p_keypair=key_pair,
            noise_privkey=key_pair.private_key,
            early_data=None,
            with_noise_pipes=False,
        )

        # Create transport upgrader
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(NOISE_PROTOCOL_ID): noise_transport
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )

        # Create WebSocket transport
        transport = WebsocketTransport(upgrader)

        # Create swarm and host
        swarm = Swarm(peer_id, peer_store, upgrader, transport)
        host = BasicHost(swarm, enable_mDNS=self.enable_mdns)

        return host

    async def handle_sync_stream(self, stream: INetStream) -> None:
        """Handle incoming sync protocol streams."""
        client_id = stream.muxed_conn.peer_id.to_string()
        logger.info(f"New sync connection from client: {client_id}")
        
        try:
            # Register client
            self.connected_clients[client_id] = {
                "peer_id": client_id,
                "connected_at": time.time(),
                "last_seen": time.time(),
                "stream": stream
            }
            self.client_streams[client_id] = stream
            self.stats["clients_connected"] += 1
            
            # Send peer join notification to other clients
            peer_join_op = self.sync_protocol.create_peer_join({
                "peer_id": client_id,
                "connected_at": time.time()
            })
            await self.broadcast_operation(peer_join_op, exclude_client=client_id)
            
            # Send current connected peers to new client
            for peer_id in self.sync_protocol.get_connected_peers():
                if peer_id != client_id:
                    peer_info_op = self.sync_protocol.create_peer_join({
                        "peer_id": peer_id,
                        "connected_at": time.time()
                    })
                    await self.send_operation_to_client(client_id, peer_info_op)
            
            # Handle incoming operations
            while True:
                try:
                    data = await stream.read(4096)
                    if not data:
                        break
                        
                    # Deserialize and process operation
                    operation = self.sync_protocol.deserialize_operation(data)
                    await self.process_operation(operation, client_id)
                    
                except Exception as e:
                    logger.error(f"Error processing operation from {client_id}: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Error in sync stream handler for {client_id}: {e}")
        finally:
            # Cleanup client connection
            await self.cleanup_client(client_id)

    async def process_operation(self, operation: SyncOperation, from_client: str) -> None:
        """Process a sync operation from a client."""
        self.stats["operations_processed"] += 1
        
        # Update client last seen
        if from_client in self.connected_clients:
            self.connected_clients[from_client]["last_seen"] = time.time()
        
        # Apply operation locally
        applied = self.sync_protocol.apply_operation(operation)
        
        if applied:
            logger.debug(f"Applied operation {operation.id} from {from_client}")
            
            # Send acknowledgment back to sender
            ack = self.sync_protocol.create_ack(operation.id)
            await self.send_operation_to_client(from_client, ack)
            
            # Broadcast to other clients (except sender)
            if operation.operation not in [OperationType.ACK, OperationType.HEARTBEAT]:
                await self.broadcast_operation(operation, exclude_client=from_client)
        else:
            logger.debug(f"Rejected operation {operation.id} from {from_client}")

    async def send_operation_to_client(self, client_id: str, operation: SyncOperation) -> None:
        """Send an operation to a specific client."""
        if client_id in self.client_streams:
            try:
                stream = self.client_streams[client_id]
                data = self.sync_protocol.serialize_operation(operation)
                await stream.write(data)
            except Exception as e:
                logger.error(f"Failed to send operation to {client_id}: {e}")
                await self.cleanup_client(client_id)

    async def broadcast_operation(self, operation: SyncOperation, exclude_client: Optional[str] = None) -> None:
        """Broadcast an operation to all connected clients except the excluded one."""
        for client_id in list(self.client_streams.keys()):
            if client_id != exclude_client:
                await self.send_operation_to_client(client_id, operation)

    async def cleanup_client(self, client_id: str) -> None:
        """Clean up a disconnected client."""
        logger.info(f"Cleaning up client: {client_id}")
        
        # Remove from connected clients
        if client_id in self.connected_clients:
            del self.connected_clients[client_id]
        
        # Remove stream
        if client_id in self.client_streams:
            stream = self.client_streams[client_id]
            try:
                await stream.close()
            except Exception:
                pass
            del self.client_streams[client_id]
        
        # Send peer leave notification
        peer_leave_op = self.sync_protocol.create_peer_leave(client_id)
        await self.broadcast_operation(peer_leave_op)
        
        self.stats["clients_connected"] = max(0, self.stats["clients_connected"] - 1)

    async def heartbeat_task(self) -> None:
        """Send periodic heartbeats to maintain connection health."""
        while self.running:
            try:
                # Send heartbeat to all connected clients
                heartbeat = self.sync_protocol.create_heartbeat()
                await self.broadcast_operation(heartbeat)
                
                # Cleanup old operations
                self.sync_protocol.cleanup_old_operations()
                
                # Log statistics
                if self.debug:
                    stats = self.sync_protocol.get_stats()
                    logger.debug(f"Sync stats: {stats}")
                
                await trio.sleep(10)  # Heartbeat every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in heartbeat task: {e}")
                await trio.sleep(5)

    async def cleanup_task(self) -> None:
        """Periodic cleanup of stale connections."""
        while self.running:
            try:
                current_time = time.time()
                stale_clients = []
                
                # Find stale clients (no activity for 60 seconds)
                for client_id, client_info in self.connected_clients.items():
                    if current_time - client_info["last_seen"] > 60:
                        stale_clients.append(client_id)
                
                # Cleanup stale clients
                for client_id in stale_clients:
                    logger.info(f"Removing stale client: {client_id}")
                    await self.cleanup_client(client_id)
                
                await trio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await trio.sleep(10)

    async def start_websocket_server(self) -> None:
        """Start WebSocket server for browser clients."""
        try:
            import websockets
            from websockets.server import WebSocketServerProtocol
            
            async def websocket_handler(websocket: WebSocketServerProtocol, path: str):
                """Handle WebSocket connections from browser clients."""
                client_id = f"browser_{uuid.uuid4().hex[:8]}"
                logger.info(f"New WebSocket connection: {client_id}")
                
                self.websocket_clients.add(websocket)
                
                try:
                    # Register as browser client
                    self.connected_clients[client_id] = {
                        "peer_id": client_id,
                        "connected_at": time.time(),
                        "last_seen": time.time(),
                        "type": "websocket"
                    }
                    
                    # Send welcome message
                    welcome_op = self.sync_protocol.create_peer_join({
                        "peer_id": client_id,
                        "type": "browser",
                        "connected_at": time.time()
                    })
                    await self.broadcast_operation(welcome_op, exclude_client=client_id)
                    
                    # Handle messages
                    async for message in websocket:
                        try:
                            # Parse JSON message
                            data = json.loads(message)
                            
                            # Create operation from browser data
                            operation = SyncOperation(
                                type=data.get("type", "operation"),
                                operation=OperationType(data.get("operation", "INSERT")),
                                id=data.get("id", f"{client_id}_{int(time.time())}"),
                                timestamp=data.get("timestamp", time.time()),
                                client_id=client_id,
                                data=data.get("data", {})
                            )
                            
                            await self.process_operation(operation, client_id)
                            
                        except Exception as e:
                            logger.error(f"Error processing WebSocket message: {e}")
                            
                except websockets.exceptions.ConnectionClosed:
                    pass
                except Exception as e:
                    logger.error(f"WebSocket handler error: {e}")
                finally:
                    self.websocket_clients.discard(websocket)
                    await self.cleanup_client(client_id)
            
            # Start WebSocket server
            self.websocket_server = await websockets.serve(
                websocket_handler, 
                "0.0.0.0", 
                self.port + 1,  # Use port + 1 for WebSocket
                subprotocols=["sync-protocol"]
            )
            
            logger.info(f"WebSocket server started on port {self.port + 1}")
            
        except ImportError:
            logger.warning("websockets library not available, WebSocket server disabled")
        except Exception as e:
            logger.error(f"Failed to start WebSocket server: {e}")

    async def run(self) -> None:
        """Run the backend peer."""
        logger.info("Starting Backend Peer...")
        
        # Create host
        self.host = self.create_host()
        
        # Set up sync protocol handler
        self.host.set_stream_handler(SYNC_PROTOCOL_ID, self.handle_sync_stream)
        
        # Configure listening addresses
        listen_addrs = get_available_interfaces(self.port)
        websocket_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}/ws")
        listen_addrs.append(websocket_addr)
        
        self.running = True
        
        try:
            async with self.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
                # Start background tasks
                nursery.start_soon(self.heartbeat_task)
                nursery.start_soon(self.cleanup_task)
                nursery.start_soon(self.host.get_peerstore().start_cleanup_task, 60)
                
                # Start WebSocket server
                nursery.start_soon(self.start_websocket_server)
                
                # Log startup information
                addrs = self.host.get_addrs()
                logger.info("Backend Peer Started Successfully!")
                logger.info("=" * 50)
                logger.info(f"Peer ID: {self.host.get_id().pretty()}")
                logger.info(f"Listening on:")
                for addr in addrs:
                    logger.info(f"  {addr}")
                logger.info(f"WebSocket: ws://localhost:{self.port + 1}")
                logger.info("=" * 50)
                logger.info("Waiting for client connections...")
                
                # Keep running
                await trio.sleep_forever()
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.running = False
            if self.websocket_server:
                self.websocket_server.close()
                await self.websocket_server.wait_closed()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Backend Peer for Browser-to-Backend P2P Sync")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--no-mdns", action="store_true", help="Disable mDNS discovery")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create and run backend peer
    peer = BackendPeer(
        port=args.port,
        enable_mdns=not args.no_mdns,
        debug=args.debug
    )
    
    try:
        trio.run(peer.run)
    except KeyboardInterrupt:
        print("\n✅ Clean exit completed.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
