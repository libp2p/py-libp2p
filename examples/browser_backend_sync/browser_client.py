"""
Browser Client for Browser-to-Backend P2P Sync

This module implements a client that can connect to the backend peer via WebSocket
and participate in real-time synchronization. It's designed to work in both
browser environments and as a standalone Python client.
"""

import argparse
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set
import trio

from sync_protocol import SyncProtocol, OperationType, SyncOperation

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BrowserSyncClient:
    """
    Client for connecting to backend peer and participating in sync.
    
    This client can work in both browser and Python environments,
    providing a unified interface for real-time synchronization.
    """

    def __init__(self, client_id: Optional[str] = None, debug: bool = False):
        self.client_id = client_id or f"client_{uuid.uuid4().hex[:8]}"
        self.debug = debug
        
        # Sync protocol
        self.sync_protocol = SyncProtocol(self.client_id)
        
        # Connection state
        self.connected = False
        self.websocket = None
        self.backend_url = None
        
        # Event handlers
        self.event_handlers: Dict[str, List[Callable]] = {
            'connected': [],
            'disconnected': [],
            'operation': [],
            'peer_join': [],
            'peer_leave': [],
            'error': []
        }
        
        # Local state for demo applications
        self.local_state: Dict[str, Any] = {}
        
        # Statistics
        self.stats = {
            "operations_sent": 0,
            "operations_received": 0,
            "connected_at": None,
            "last_operation": None
        }

    def on(self, event: str, handler: Callable) -> None:
        """Register an event handler."""
        if event in self.event_handlers:
            self.event_handlers[event].append(handler)

    def emit(self, event: str, *args, **kwargs) -> None:
        """Emit an event to all registered handlers."""
        if event in self.event_handlers:
            for handler in self.event_handlers[event]:
                try:
                    handler(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error in event handler for {event}: {e}")

    async def connect(self, backend_url: str) -> None:
        """Connect to the backend peer via WebSocket."""
        self.backend_url = backend_url
        
        try:
            # Try to import websockets for Python environment
            try:
                import websockets
                await self._connect_python(backend_url)
            except ImportError:
                # Browser environment - would use browser WebSocket API
                await self._connect_browser(backend_url)
                
        except Exception as e:
            logger.error(f"Failed to connect to backend: {e}")
            self.emit('error', e)
            raise

    async def _connect_python(self, backend_url: str) -> None:
        """Connect using Python websockets library."""
        import websockets
        
        logger.info(f"Connecting to backend: {backend_url}")
        
        self.websocket = await websockets.connect(
            backend_url,
            subprotocols=["sync-protocol"]
        )
        
        self.connected = True
        self.stats["connected_at"] = time.time()
        
        logger.info("Connected to backend peer")
        self.emit('connected')
        
        # Start message handling
        await self._handle_messages()

    async def _connect_browser(self, backend_url: str) -> None:
        """Connect using browser WebSocket API (placeholder for browser implementation)."""
        # This would be implemented in JavaScript for browser environments
        logger.info("Browser WebSocket connection (placeholder)")
        self.connected = True
        self.stats["connected_at"] = time.time()
        self.emit('connected')

    async def _handle_messages(self) -> None:
        """Handle incoming WebSocket messages."""
        try:
            async for message in self.websocket:
                try:
                    # Parse JSON message
                    data = json.loads(message)
                    
                    # Create operation from received data
                    operation = SyncOperation(
                        type=data.get("type", "operation"),
                        operation=OperationType(data.get("operation", "INSERT")),
                        id=data.get("id", f"unknown_{int(time.time())}"),
                        timestamp=data.get("timestamp", time.time()),
                        client_id=data.get("client_id", "unknown"),
                        data=data.get("data", {})
                    )
                    
                    await self._process_operation(operation)
                    
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    self.emit('error', e)
                    
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
            self.emit('error', e)
        finally:
            await self.disconnect()

    async def _process_operation(self, operation: SyncOperation) -> None:
        """Process a received operation."""
        self.stats["operations_received"] += 1
        self.stats["last_operation"] = time.time()
        
        # Apply operation locally
        applied = self.sync_protocol.apply_operation(operation)
        
        if applied:
            logger.debug(f"Applied operation {operation.id} from {operation.client_id}")
            
            # Emit appropriate events
            if operation.operation == OperationType.PEER_JOIN:
                self.emit('peer_join', operation.data)
            elif operation.operation == OperationType.PEER_LEAVE:
                self.emit('peer_leave', operation.data)
            elif operation.operation not in [OperationType.ACK, OperationType.HEARTBEAT]:
                self.emit('operation', operation)
        else:
            logger.debug(f"Rejected operation {operation.id} from {operation.client_id}")

    async def send_operation(
        self,
        operation_type: OperationType,
        data: Dict[str, Any],
        parent_id: Optional[str] = None
    ) -> str:
        """Send an operation to the backend peer."""
        if not self.connected:
            raise RuntimeError("Not connected to backend peer")
        
        # Create operation
        operation = self.sync_protocol.create_operation(operation_type, data, parent_id)
        
        # Serialize and send
        message = json.dumps(operation.to_dict())
        
        if self.websocket:
            await self.websocket.send(message)
        
        self.stats["operations_sent"] += 1
        logger.debug(f"Sent operation {operation.id}: {operation_type.value}")
        
        return operation.id

    async def send_data(self, data: Dict[str, Any]) -> str:
        """Send data using INSERT operation."""
        return await self.send_operation(OperationType.INSERT, data)

    async def update_data(self, data: Dict[str, Any]) -> str:
        """Send data using UPDATE operation."""
        return await self.send_operation(OperationType.UPDATE, data)

    async def delete_data(self, data: Dict[str, Any]) -> str:
        """Send data using DELETE operation."""
        return await self.send_operation(OperationType.DELETE, data)

    async def disconnect(self) -> None:
        """Disconnect from the backend peer."""
        if self.connected:
            self.connected = False
            
            if self.websocket:
                await self.websocket.close()
                self.websocket = None
            
            logger.info("Disconnected from backend peer")
            self.emit('disconnected')

    def get_connected_peers(self) -> List[str]:
        """Get list of connected peers."""
        return self.sync_protocol.get_connected_peers()

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        sync_stats = self.sync_protocol.get_stats()
        return {
            **self.stats,
            **sync_stats,
            "connected": self.connected
        }


class NotepadClient(BrowserSyncClient):
    """
    Specialized client for collaborative notepad functionality.
    """

    def __init__(self, client_id: Optional[str] = None, debug: bool = False):
        super().__init__(client_id, debug)
        
        # Notepad-specific state
        self.document = ""
        self.cursor_position = 0
        self.operations: List[Dict] = []
        
        # Set up event handlers
        self.on('operation', self._handle_notepad_operation)
        self.on('peer_join', self._handle_peer_join)
        self.on('peer_leave', self._handle_peer_leave)

    def _handle_notepad_operation(self, operation: SyncOperation) -> None:
        """Handle notepad-specific operations."""
        if operation.operation == OperationType.INSERT:
            self._apply_insert(operation.data)
        elif operation.operation == OperationType.DELETE:
            self._apply_delete(operation.data)
        elif operation.operation == OperationType.UPDATE:
            self._apply_update(operation.data)

    def _apply_insert(self, data: Dict[str, Any]) -> None:
        """Apply insert operation to local document."""
        position = data.get("position", 0)
        content = data.get("content", "")
        
        if 0 <= position <= len(self.document):
            self.document = self.document[:position] + content + self.document[position:]
            self.operations.append({
                "type": "insert",
                "position": position,
                "content": content,
                "timestamp": time.time()
            })

    def _apply_delete(self, data: Dict[str, Any]) -> None:
        """Apply delete operation to local document."""
        position = data.get("position", 0)
        length = data.get("length", 1)
        
        if 0 <= position < len(self.document):
            end_pos = min(position + length, len(self.document))
            deleted_content = self.document[position:end_pos]
            self.document = self.document[:position] + self.document[end_pos:]
            self.operations.append({
                "type": "delete",
                "position": position,
                "length": length,
                "content": deleted_content,
                "timestamp": time.time()
            })

    def _apply_update(self, data: Dict[str, Any]) -> None:
        """Apply update operation to local document."""
        if "document" in data:
            self.document = data["document"]
            self.operations.append({
                "type": "update",
                "document": data["document"],
                "timestamp": time.time()
            })

    def _handle_peer_join(self, data: Dict[str, Any]) -> None:
        """Handle peer join event."""
        peer_id = data.get("peer_id", "unknown")
        logger.info(f"Peer joined: {peer_id}")

    def _handle_peer_leave(self, data: Dict[str, Any]) -> None:
        """Handle peer leave event."""
        peer_id = data.get("peer_id", "unknown")
        logger.info(f"Peer left: {peer_id}")

    async def insert_text(self, position: int, text: str) -> str:
        """Insert text at the specified position."""
        return await self.send_operation(OperationType.INSERT, {
            "position": position,
            "content": text
        })

    async def delete_text(self, position: int, length: int = 1) -> str:
        """Delete text at the specified position."""
        return await self.send_operation(OperationType.DELETE, {
            "position": position,
            "length": length
        })

    async def update_document(self, document: str) -> str:
        """Update the entire document."""
        return await self.send_operation(OperationType.UPDATE, {
            "document": document
        })

    def get_document(self) -> str:
        """Get the current document content."""
        return self.document

    def get_operations(self) -> List[Dict]:
        """Get the list of operations."""
        return self.operations


async def demo_notepad_client(backend_url: str, client_id: str) -> None:
    """Demo function showing notepad client usage."""
    client = NotepadClient(client_id, debug=True)
    
    # Set up event handlers
    def on_connected():
        print(f"✅ Connected as {client_id}")
    
    def on_operation(operation):
        print(f"📝 Operation: {operation.operation.value} - {operation.data}")
    
    def on_peer_join(data):
        print(f"👋 Peer joined: {data.get('peer_id')}")
    
    def on_peer_leave(data):
        print(f"👋 Peer left: {data.get('peer_id')}")
    
    client.on('connected', on_connected)
    client.on('operation', on_operation)
    client.on('peer_join', on_peer_join)
    client.on('peer_leave', on_peer_leave)
    
    try:
        # Connect to backend
        await client.connect(backend_url)
        
        # Wait a bit for connection to stabilize
        await trio.sleep(1)
        
        # Demo operations
        print("📝 Demo notepad operations:")
        
        # Insert some text
        await client.insert_text(0, "Hello, ")
        await trio.sleep(0.5)
        
        await client.insert_text(7, "World!")
        await trio.sleep(0.5)
        
        # Update cursor position
        await client.send_operation(OperationType.UPDATE, {
            "cursor_position": 12
        })
        
        # Show current document
        print(f"📄 Document: '{client.get_document()}'")
        
        # Keep running to receive operations from other clients
        print("⏳ Listening for operations from other clients...")
        print("   (Press Ctrl+C to exit)")
        
        await trio.sleep_forever()
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        await client.disconnect()


def main():
    """Main entry point for browser client demo."""
    parser = argparse.ArgumentParser(description="Browser Client for P2P Sync")
    parser.add_argument("--backend-url", required=True, help="Backend WebSocket URL")
    parser.add_argument("--client-id", help="Client ID (auto-generated if not provided)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        trio.run(demo_notepad_client, args.backend_url, args.client_id or f"client_{uuid.uuid4().hex[:8]}")
    except KeyboardInterrupt:
        print("\n✅ Clean exit completed.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
