"""
Main P2P File Sharing Application.

This module provides the main application class that coordinates all components
for P2P file sharing including NAT traversal, peer management, and file operations.
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

from .file_protocol import FileSharingProtocol, FileInfo, ProtocolMessage, MessageType
from .nat_traversal import NATTraversalManager
from .peer_manager import PeerManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("libp2p.file_sharing.app")

# Protocol ID for file sharing
FILE_SHARING_PROTOCOL = TProtocol("/p2p/file-sharing/1.0.0")


class P2PFileSharingApp:
    """
    Main P2P File Sharing Application.
    
    This class coordinates all components for peer-to-peer file sharing
    including NAT traversal, peer discovery, and file operations.
    """

    def __init__(
        self,
        port: int = 0,
        shared_files_dir: str = "./shared_files",
        download_dir: str = "./downloads",
        peer_db_path: str = "./peer_database.json",
        seed: Optional[int] = None
    ):
        """
        Initialize the P2P file sharing application.

        Args:
            port: Port to listen on (0 for auto-assign)
            shared_files_dir: Directory containing files to share
            download_dir: Directory to save downloaded files
            peer_db_path: Path to persistent peer database
            seed: Seed for deterministic peer ID generation
        """
        self.port = port if port > 0 else find_free_port()
        self.shared_files_dir = shared_files_dir
        self.download_dir = download_dir
        self.peer_db_path = peer_db_path
        
        # Create directories
        os.makedirs(shared_files_dir, exist_ok=True)
        os.makedirs(download_dir, exist_ok=True)
        
        # Initialize components
        self.host = None
        self.file_protocol: Optional[FileSharingProtocol] = None
        self.nat_traversal: Optional[NATTraversalManager] = None
        self.peer_manager: Optional[PeerManager] = None
        
        # Application state
        self.is_running = False
        self.connected_peers: Dict[str, str] = {}  # peer_id -> peer_name
        
        # Initialize host with deterministic key if seed provided
        self._initialize_host(seed)

    def _initialize_host(self, seed: Optional[int] = None) -> None:
        """Initialize the libp2p host."""
        if seed:
            import random
            import secrets
            random.seed(seed)
            secret_number = random.getrandbits(32 * 8)
            secret = secret_number.to_bytes(length=32, byteorder="big")
        else:
            secret = secrets.token_bytes(32)
        
        self.host = new_host(key_pair=create_new_key_pair(secret))

    async def initialize(self) -> None:
        """Initialize all application components."""
        logger.info("Initializing P2P File Sharing Application...")
        
        # Initialize file protocol
        self.file_protocol = FileSharingProtocol(self.shared_files_dir)
        
        # Initialize NAT traversal
        self.nat_traversal = NATTraversalManager(self.host)
        await self.nat_traversal.initialize()
        
        # Initialize peer manager
        self.peer_manager = PeerManager(self.host, self.peer_db_path)
        await self.peer_manager.initialize_discovery()
        
        # Set up file sharing protocol handler
        self.host.set_stream_handler(FILE_SHARING_PROTOCOL, self._handle_file_sharing_stream)
        
        # Start peer maintenance
        await self.peer_manager.start_peer_maintenance()
        
        logger.info("Application initialized successfully")

    async def shutdown(self) -> None:
        """Shutdown the application."""
        logger.info("Shutting down P2P File Sharing Application...")
        
        self.is_running = False
        
        if self.nat_traversal:
            await self.nat_traversal.shutdown()
        
        if self.peer_manager:
            await self.peer_manager.shutdown_discovery()
        
        logger.info("Application shut down")

    async def _handle_file_sharing_stream(self, stream: INetStream) -> None:
        """Handle incoming file sharing protocol streams."""
        if self.file_protocol:
            await self.file_protocol.handle_stream(stream)

    async def start(self) -> None:
        """Start the application."""
        logger.info("Starting P2P File Sharing Application...")
        
        # Get listen addresses
        listen_addrs = get_available_interfaces(self.port)
        
        # Start the host
        async with self.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
            # Start the peer-store cleanup task
            nursery.start_soon(self.host.get_peerstore().start_cleanup_task, 60)
            
            # Initialize components
            await self.initialize()
            
            self.is_running = True
            
            # Print connection information
            self._print_connection_info()
            
            # Start interactive mode
            await self._interactive_mode()

    def _print_connection_info(self) -> None:
        """Print connection information for other peers."""
        peer_id = self.host.get_id().to_string()
        all_addrs = self.host.get_addrs()
        
        print("\n" + "="*60)
        print("🚀 P2P File Sharing Application Started")
        print("="*60)
        print(f"Peer ID: {peer_id}")
        print(f"Listening on:")
        for addr in all_addrs:
            print(f"  {addr}")
        
        # Get optimal address for easy copying
        optimal_addr = get_optimal_binding_address(self.port)
        optimal_addr_with_peer = f"{optimal_addr}/p2p/{peer_id}"
        print(f"\n📋 Share this address with other peers:")
        print(f"  {optimal_addr_with_peer}")
        print("="*60)

    async def _interactive_mode(self) -> None:
        """Run the interactive command interface."""
        print("\n📁 Available commands:")
        print("  list-files          - List available files")
        print("  list-peers          - List connected peers")
        print("  connect <address>   - Connect to a peer")
        print("  download <hash>     - Download a file by hash")
        print("  share <file>        - Add a file to shared files")
        print("  stats               - Show connection statistics")
        print("  help                - Show this help")
        print("  quit                - Exit the application")
        print("\n💡 Type 'help' for more information on commands")
        
        while self.is_running:
            try:
                # Read user input
                command = await trio.to_thread.run_sync(input, "p2p-fileshare> ")
                command = command.strip()
                
                if not command:
                    continue
                
                # Parse and execute command
                await self._execute_command(command)
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except EOFError:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")

    async def _execute_command(self, command: str) -> None:
        """Execute a user command."""
        parts = command.split()
        cmd = parts[0].lower()
        
        if cmd == "help":
            self._show_help()
        elif cmd == "list-files":
            await self._list_files()
        elif cmd == "list-peers":
            await self._list_peers()
        elif cmd == "connect":
            if len(parts) < 2:
                print("❌ Usage: connect <peer_address>")
            else:
                await self._connect_to_peer(parts[1])
        elif cmd == "download":
            if len(parts) < 2:
                print("❌ Usage: download <file_hash>")
            else:
                await self._download_file(parts[1])
        elif cmd == "share":
            if len(parts) < 2:
                print("❌ Usage: share <file_path>")
            else:
                await self._share_file(parts[1])
        elif cmd == "stats":
            await self._show_stats()
        elif cmd == "quit" or cmd == "exit":
            self.is_running = False
        else:
            print(f"❌ Unknown command: {cmd}")
            print("💡 Type 'help' for available commands")

    def _show_help(self) -> None:
        """Show detailed help information."""
        print("\n📖 P2P File Sharing Commands:")
        print("  list-files          - List all available files from connected peers")
        print("  list-peers          - List all connected peers")
        print("  connect <address>   - Connect to a peer using their multiaddress")
        print("  download <hash>     - Download a file using its SHA256 hash")
        print("  share <file>        - Add a local file to your shared files")
        print("  stats               - Show connection and NAT traversal statistics")
        print("  help                - Show this help message")
        print("  quit/exit           - Exit the application")
        print("\n💡 Examples:")
        print("  connect /ip4/192.168.1.100/tcp/8000/p2p/QmPeerId...")
        print("  download a1b2c3d4e5f6...")
        print("  share /path/to/my/file.txt")

    async def _list_files(self) -> None:
        """List available files from all connected peers."""
        print("\n📁 Available Files:")
        
        connected_peers = self.peer_manager.get_connected_peers()
        if not connected_peers:
            print("  No connected peers. Use 'connect' to connect to peers.")
            return
        
        total_files = 0
        for peer_id in connected_peers:
            try:
                # Create stream to peer
                stream = await self.host.new_stream(peer_id, [FILE_SHARING_PROTOCOL])
                
                # Request file list
                files = await self.file_protocol.request_file_list(stream)
                
                if files:
                    print(f"\n  📂 From peer {peer_id.to_base58()[:12]}...:")
                    for file_info in files:
                        size_mb = file_info.size / (1024 * 1024)
                        print(f"    📄 {file_info.name}")
                        print(f"       Size: {size_mb:.2f} MB")
                        print(f"       Hash: {file_info.hash}")
                        if file_info.description:
                            print(f"       Description: {file_info.description}")
                        print()
                    total_files += len(files)
                
                await stream.close()
                
            except Exception as e:
                print(f"  ❌ Failed to get files from peer {peer_id.to_base58()[:12]}...: {e}")
        
        if total_files == 0:
            print("  No files available from connected peers.")
        else:
            print(f"  Total files available: {total_files}")

    async def _list_peers(self) -> None:
        """List connected peers."""
        print("\n👥 Connected Peers:")
        
        connected_peers = self.peer_manager.get_connected_peers()
        if not connected_peers:
            print("  No connected peers.")
            return
        
        for peer_id in connected_peers:
            try:
                peer_info = self.host.get_peerstore().peer_info(peer_id)
                print(f"  🔗 {peer_id.to_base58()[:12]}...")
                for addr in peer_info.addrs:
                    print(f"     {addr}")
            except Exception as e:
                print(f"  ❌ Error getting info for peer {peer_id.to_base58()[:12]}...: {e}")

    async def _connect_to_peer(self, address: str) -> None:
        """Connect to a peer using their multiaddress."""
        try:
            print(f"🔗 Connecting to peer: {address}")
            
            # Parse peer info from address
            peer_info = info_from_p2p_addr(address)
            
            # Add peer to peer manager
            self.peer_manager.add_peer(peer_info)
            
            # Attempt connection with NAT traversal
            success = await self.nat_traversal.connect_with_nat_traversal(peer_info)
            
            if success:
                print(f"✅ Successfully connected to peer: {peer_info.peer_id.to_base58()[:12]}...")
            else:
                print(f"❌ Failed to connect to peer: {peer_info.peer_id.to_base58()[:12]}...")
                
        except Exception as e:
            print(f"❌ Connection failed: {e}")

    async def _download_file(self, file_hash: str) -> None:
        """Download a file by its hash."""
        print(f"⬇️  Downloading file with hash: {file_hash}")
        
        connected_peers = self.peer_manager.get_connected_peers()
        if not connected_peers:
            print("❌ No connected peers available for download.")
            return
        
        # Try to download from each connected peer
        for peer_id in connected_peers:
            try:
                print(f"🔍 Searching for file on peer: {peer_id.to_base58()[:12]}...")
                
                # Create stream to peer
                stream = await self.host.new_stream(peer_id, [FILE_SHARING_PROTOCOL])
                
                # Request file list to find the file
                files = await self.file_protocol.request_file_list(stream)
                await stream.close()
                
                # Check if peer has the file
                target_file = None
                for file_info in files:
                    if file_info.hash == file_hash:
                        target_file = file_info
                        break
                
                if not target_file:
                    print(f"  File not found on peer {peer_id.to_base58()[:12]}...")
                    continue
                
                print(f"  📄 Found file: {target_file.name}")
                
                # Create new stream for download
                stream = await self.host.new_stream(peer_id, [FILE_SHARING_PROTOCOL])
                
                # Download the file
                save_path = os.path.join(self.download_dir, target_file.name)
                await self.file_protocol.download_file(stream, file_hash, save_path)
                await stream.close()
                
                print(f"✅ File downloaded successfully: {save_path}")
                return
                
            except Exception as e:
                print(f"  ❌ Download failed from peer {peer_id.to_base58()[:12]}...: {e}")
        
        print("❌ File not found on any connected peer.")

    async def _share_file(self, file_path: str) -> None:
        """Add a file to shared files."""
        try:
            if not os.path.exists(file_path):
                print(f"❌ File not found: {file_path}")
                return
            
            # Copy file to shared directory
            filename = os.path.basename(file_path)
            shared_path = os.path.join(self.shared_files_dir, filename)
            
            # Handle duplicate filenames
            counter = 1
            base_name, ext = os.path.splitext(filename)
            while os.path.exists(shared_path):
                new_filename = f"{base_name}_{counter}{ext}"
                shared_path = os.path.join(self.shared_files_dir, new_filename)
                counter += 1
            
            # Copy file
            import shutil
            shutil.copy2(file_path, shared_path)
            
            # Refresh file protocol
            self.file_protocol._refresh_file_list()
            
            print(f"✅ File shared successfully: {os.path.basename(shared_path)}")
            
        except Exception as e:
            print(f"❌ Failed to share file: {e}")

    async def _show_stats(self) -> None:
        """Show connection and NAT traversal statistics."""
        print("\n📊 Application Statistics:")
        
        # Peer statistics
        peer_stats = self.peer_manager.get_peer_stats()
        print(f"  👥 Known peers: {peer_stats['known_peers']}")
        print(f"  🔗 Connected peers: {peer_stats['connected_peers']}")
        print(f"  ❌ Failed peers: {peer_stats['failed_peers']}")
        print(f"  ⏰ Expired peers: {peer_stats['expired_peers']}")
        
        # NAT traversal statistics
        nat_stats = self.nat_traversal.get_connection_stats()
        print(f"  🌐 NAT status: {nat_stats['nat_status']}")
        print(f"  📡 Direct connections: {nat_stats['direct_connections']}")
        print(f"  🔄 Relay connections: {nat_stats['relay_connections']}")
        print(f"  ❌ Failed connections: {nat_stats['failed_connections']}")
        print(f"  🚀 Discovered relays: {nat_stats['discovered_relays']}")
        
        # File statistics
        shared_files = self.file_protocol.get_file_list()
        print(f"  📁 Shared files: {len(shared_files)}")
        
        # Application uptime
        if hasattr(self, '_start_time'):
            uptime = time.time() - self._start_time
            hours = int(uptime // 3600)
            minutes = int((uptime % 3600) // 60)
            print(f"  ⏱️  Uptime: {hours}h {minutes}m")


async def main():
    """Main entry point for the P2P file sharing application."""
    parser = argparse.ArgumentParser(
        description="P2P File Sharing Application with NAT Traversal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start as a server (listener)
  python -m examples.p2p_file_sharing.file_sharing_app

  # Start with specific port
  python -m examples.p2p_file_sharing.file_sharing_app --port 8000

  # Start with custom directories
  python -m examples.p2p_file_sharing.file_sharing_app --shared-dir ./my_files --download-dir ./downloads

  # Start with deterministic peer ID (for testing)
  python -m examples.p2p_file_sharing.file_sharing_app --seed 12345
        """
    )
    
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=0,
        help="Port to listen on (default: auto-assign)"
    )
    
    parser.add_argument(
        "--shared-dir",
        type=str,
        default="./shared_files",
        help="Directory containing files to share (default: ./shared_files)"
    )
    
    parser.add_argument(
        "--download-dir",
        type=str,
        default="./downloads",
        help="Directory to save downloaded files (default: ./downloads)"
    )
    
    parser.add_argument(
        "--peer-db",
        type=str,
        default="./peer_database.json",
        help="Path to persistent peer database (default: ./peer_database.json)"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        help="Seed for deterministic peer ID generation (useful for testing)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("libp2p").setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("libp2p").setLevel(logging.WARNING)
    
    # Create and run application
    app = P2PFileSharingApp(
        port=args.port,
        shared_files_dir=args.shared_dir,
        download_dir=args.download_dir,
        peer_db_path=args.peer_db,
        seed=args.seed
    )
    
    try:
        await app.start()
    except KeyboardInterrupt:
        print("\n👋 Application interrupted by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
    finally:
        await app.shutdown()


if __name__ == "__main__":
    trio.run(main)
