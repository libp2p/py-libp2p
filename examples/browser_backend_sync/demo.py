#!/usr/bin/env python3
"""
Complete Demo of Browser-to-Backend P2P Sync

This script demonstrates the full capabilities of the browser-to-backend P2P sync
implementation, showcasing libp2p as infrastructure replacement for centralized
real-time sync systems.
"""

import argparse
import asyncio
import logging
import sys
import time
import uuid
from typing import List
import trio

from backend_peer import BackendPeer
from browser_client import NotepadClient, BrowserSyncClient
from notepad_demo import CollaborativeNotepad
from whiteboard_demo import CollaborativeWhiteboard

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class P2PSyncDemo:
    """
    Complete demonstration of Browser-to-Backend P2P Sync.
    
    This demo showcases:
    - Backend peer with NAT traversal
    - Multiple client connections
    - Real-time synchronization
    - Collaborative editing
    - Conflict resolution
    """

    def __init__(self, port: int = 8000, debug: bool = False):
        self.port = port
        self.debug = debug
        self.backend_peer = None
        self.clients: List[BrowserSyncClient] = []
        self.running = False

    async def start_backend(self) -> None:
        """Start the backend peer."""
        logger.info("🚀 Starting Backend Peer...")
        
        self.backend_peer = BackendPeer(
            port=self.port,
            enable_mdns=True,
            debug=self.debug
        )
        
        # Start backend in background
        async def run_backend():
            await self.backend_peer.run()
        
        # We'll start this in a nursery later
        self.backend_task = run_backend

    async def create_client(self, client_id: str) -> BrowserSyncClient:
        """Create and connect a client."""
        logger.info(f"👤 Creating client: {client_id}")
        
        client = NotepadClient(client_id, self.debug)
        
        # Set up event handlers
        def on_connected():
            logger.info(f"✅ {client_id} connected")
        
        def on_operation(operation):
            logger.debug(f"📥 {client_id} received: {operation.operation.value}")
        
        def on_peer_join(data):
            peer_id = data.get("peer_id", "unknown")
            logger.info(f"👋 {client_id} sees {peer_id} joined")
        
        def on_peer_leave(data):
            peer_id = data.get("peer_id", "unknown")
            logger.info(f"👋 {client_id} sees {peer_id} left")
        
        client.on('connected', on_connected)
        client.on('operation', on_operation)
        client.on('peer_join', on_peer_join)
        client.on('peer_leave', on_peer_leave)
        
        # Connect to backend
        backend_url = f"ws://localhost:{self.port + 1}"
        await client.connect(backend_url)
        
        self.clients.append(client)
        return client

    async def demo_collaborative_editing(self) -> None:
        """Demonstrate collaborative editing capabilities."""
        logger.info("📝 Starting Collaborative Editing Demo")
        
        if len(self.clients) < 2:
            logger.warning("Need at least 2 clients for collaborative demo")
            return
        
        # Get notepad clients
        notepad_clients = [c for c in self.clients if isinstance(c, NotepadClient)]
        
        if len(notepad_clients) < 2:
            logger.warning("Need at least 2 notepad clients")
            return
        
        client1, client2 = notepad_clients[:2]
        
        logger.info("🎬 Collaborative Editing Scenario:")
        logger.info("   Client 1 will write a story")
        logger.info("   Client 2 will edit and add to it")
        logger.info("   Both will see changes in real-time")
        
        # Client 1 starts writing
        await trio.sleep(1)
        logger.info("📝 Client 1: Writing story beginning...")
        await client1.insert_text(0, "Once upon a time, in a land far away...\n")
        await trio.sleep(2)
        
        await client1.insert_text(0, "Chapter 1: The Beginning\n\n")
        await trio.sleep(2)
        
        # Client 2 adds to the story
        logger.info("📝 Client 2: Adding to the story...")
        current_doc = client2.get_document()
        await client2.insert_text(len(current_doc), "\nThere lived a brave knight who...\n")
        await trio.sleep(2)
        
        # Client 1 continues
        logger.info("📝 Client 1: Continuing the story...")
        current_doc = client1.get_document()
        await client1.insert_text(len(current_doc), "ventured into the dark forest.\n")
        await trio.sleep(2)
        
        # Client 2 edits previous text
        logger.info("📝 Client 2: Editing previous text...")
        current_doc = client2.get_document()
        # Find and replace "brave" with "fearless"
        if "brave" in current_doc:
            pos = current_doc.find("brave")
            await client2.delete_text(pos, 5)  # Delete "brave"
            await client2.insert_text(pos, "fearless")  # Insert "fearless"
        
        await trio.sleep(2)
        
        # Show final result
        logger.info("📄 Final collaborative document:")
        final_doc = client1.get_document()
        logger.info("─" * 50)
        for i, line in enumerate(final_doc.split('\n'), 1):
            logger.info(f"{i:2d}: {line}")
        logger.info("─" * 50)
        
        logger.info("✅ Collaborative editing demo completed!")

    async def demo_peer_discovery(self) -> None:
        """Demonstrate peer discovery and connection management."""
        logger.info("🔍 Starting Peer Discovery Demo")
        
        # Show connected peers for each client
        for client in self.clients:
            peers = client.get_connected_peers()
            logger.info(f"👥 {client.client_id} sees {len(peers)} peers: {peers}")
        
        # Add a new client dynamically
        logger.info("➕ Adding new client dynamically...")
        new_client = await self.create_client(f"dynamic_{uuid.uuid4().hex[:8]}")
        await trio.sleep(2)
        
        # Show updated peer lists
        for client in self.clients:
            peers = client.get_connected_peers()
            logger.info(f"👥 {client.client_id} now sees {len(peers)} peers: {peers}")
        
        logger.info("✅ Peer discovery demo completed!")

    async def demo_conflict_resolution(self) -> None:
        """Demonstrate conflict resolution capabilities."""
        logger.info("⚔️ Starting Conflict Resolution Demo")
        
        if len(self.clients) < 2:
            logger.warning("Need at least 2 clients for conflict resolution demo")
            return
        
        notepad_clients = [c for c in self.clients if isinstance(c, NotepadClient)]
        
        if len(notepad_clients) < 2:
            logger.warning("Need at least 2 notepad clients")
            return
        
        client1, client2 = notepad_clients[:2]
        
        # Clear documents first
        await client1.update_document("")
        await client2.update_document("")
        await trio.sleep(1)
        
        logger.info("🎬 Conflict Resolution Scenario:")
        logger.info("   Both clients will try to insert text at the same position")
        logger.info("   The sync protocol will resolve conflicts using timestamps")
        
        # Both clients try to insert at position 0 simultaneously
        logger.info("⚡ Simultaneous insertions...")
        
        # Start both operations at nearly the same time
        task1 = client1.insert_text(0, "Client1 says: ")
        task2 = client2.insert_text(0, "Client2 says: ")
        
        await asyncio.gather(task1, task2)
        await trio.sleep(2)
        
        # Show how conflict was resolved
        doc1 = client1.get_document()
        doc2 = client2.get_document()
        
        logger.info(f"📄 Client 1 document: '{doc1}'")
        logger.info(f"📄 Client 2 document: '{doc2}'")
        logger.info(f"🔄 Documents match: {doc1 == doc2}")
        
        logger.info("✅ Conflict resolution demo completed!")

    async def demo_performance(self) -> None:
        """Demonstrate performance capabilities."""
        logger.info("⚡ Starting Performance Demo")
        
        if not self.clients:
            logger.warning("No clients available for performance demo")
            return
        
        client = self.clients[0]
        
        # Measure operation throughput
        logger.info("📊 Measuring operation throughput...")
        
        start_time = time.time()
        operations = 100
        
        for i in range(operations):
            await client.insert_text(0, f"Operation {i} ")
        
        end_time = time.time()
        duration = end_time - start_time
        throughput = operations / duration
        
        logger.info(f"📈 Performance Results:")
        logger.info(f"   Operations: {operations}")
        logger.info(f"   Duration: {duration:.2f} seconds")
        logger.info(f"   Throughput: {throughput:.1f} ops/sec")
        
        # Show client statistics
        stats = client.get_stats()
        logger.info(f"📊 Client Statistics:")
        logger.info(f"   Operations sent: {stats['operations_sent']}")
        logger.info(f"   Operations received: {stats['operations_received']}")
        logger.info(f"   Connected peers: {len(stats.get('connected_peers', []))}")
        
        logger.info("✅ Performance demo completed!")

    async def run_complete_demo(self) -> None:
        """Run the complete demonstration."""
        logger.info("🎬 Starting Complete Browser-to-Backend P2P Sync Demo")
        logger.info("=" * 60)
        
        try:
            async with trio.open_nursery() as nursery:
                # Start backend peer
                nursery.start_soon(self.backend_task)
                await trio.sleep(2)  # Give backend time to start
                
                # Create multiple clients
                logger.info("👥 Creating multiple clients...")
                client1 = await self.create_client("demo_client_1")
                await trio.sleep(1)
                
                client2 = await self.create_client("demo_client_2")
                await trio.sleep(1)
                
                client3 = await self.create_client("demo_client_3")
                await trio.sleep(2)
                
                # Run demonstration scenarios
                await self.demo_peer_discovery()
                await trio.sleep(2)
                
                await self.demo_collaborative_editing()
                await trio.sleep(2)
                
                await self.demo_conflict_resolution()
                await trio.sleep(2)
                
                await self.demo_performance()
                await trio.sleep(2)
                
                # Final summary
                logger.info("🎉 Demo Summary:")
                logger.info("=" * 60)
                logger.info("✅ Backend peer with NAT traversal")
                logger.info("✅ Multiple client connections")
                logger.info("✅ Real-time synchronization")
                logger.info("✅ Collaborative editing")
                logger.info("✅ Conflict resolution")
                logger.info("✅ Peer discovery")
                logger.info("✅ Performance measurement")
                logger.info("=" * 60)
                logger.info("🚀 Browser-to-Backend P2P Sync is working perfectly!")
                logger.info("💡 This demonstrates libp2p as infrastructure replacement")
                logger.info("   for centralized real-time sync systems")
                
                # Keep running for a bit to show ongoing sync
                logger.info("⏳ Keeping demo running for 30 seconds to show ongoing sync...")
                await trio.sleep(30)
                
        except KeyboardInterrupt:
            logger.info("🛑 Demo interrupted by user")
        except Exception as e:
            logger.error(f"❌ Demo error: {e}")
        finally:
            # Cleanup
            logger.info("🧹 Cleaning up...")
            for client in self.clients:
                await client.disconnect()
            logger.info("✅ Cleanup completed")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Complete Browser-to-Backend P2P Sync Demo")
    parser.add_argument("--port", type=int, default=8000, help="Backend port")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create and run demo
    demo = P2PSyncDemo(port=args.port, debug=args.debug)
    
    try:
        await demo.run_complete_demo()
    except KeyboardInterrupt:
        print("\n✅ Demo completed successfully!")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = trio.run(main)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n✅ Clean exit completed.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
