"""
Collaborative Notepad Demo

A real-time collaborative text editor demonstrating browser-to-backend P2P sync.
Multiple users can edit the same document simultaneously with conflict resolution.
"""

import argparse
import asyncio
import logging
import sys
import time
import uuid
from typing import Dict, List, Optional
import trio

from browser_client import NotepadClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CollaborativeNotepad:
    """
    Collaborative notepad with real-time synchronization.
    
    Features:
    - Real-time text editing
    - Multiple users can edit simultaneously
    - Conflict resolution for concurrent edits
    - Cursor position sharing
    - Operation history
    """

    def __init__(self, client_id: Optional[str] = None, debug: bool = False):
        self.client_id = client_id or f"notepad_{uuid.uuid4().hex[:8]}"
        self.debug = debug
        
        # Create notepad client
        self.client = NotepadClient(self.client_id, debug)
        
        # UI state
        self.cursor_position = 0
        self.selection_start = None
        self.selection_end = None
        
        # Set up event handlers
        self._setup_handlers()
        
        # Demo content
        self.demo_content = [
            "Welcome to the Collaborative Notepad!",
            "",
            "This is a demonstration of browser-to-backend P2P sync using py-libp2p.",
            "",
            "Features:",
            "• Real-time text editing",
            "• Multiple users can edit simultaneously", 
            "• Conflict resolution for concurrent edits",
            "• Cursor position sharing",
            "• Operation history",
            "",
            "Try editing this text and see how changes sync in real-time!",
            "",
            "Built with py-libp2p - the Python implementation of libp2p networking stack."
        ]

    def _setup_handlers(self) -> None:
        """Set up event handlers for the notepad client."""
        
        def on_connected():
            print(f"✅ Connected to collaborative notepad as {self.client_id}")
            print("📝 You can now start editing!")
            print("💡 Try opening another client to see real-time collaboration")
            print("─" * 60)
        
        def on_operation(operation):
            if self.debug:
                print(f"📥 Received operation: {operation.operation.value} from {operation.client_id}")
                print(f"   Data: {operation.data}")
        
        def on_peer_join(data):
            peer_id = data.get("peer_id", "unknown")
            print(f"👋 {peer_id} joined the notepad")
        
        def on_peer_leave(data):
            peer_id = data.get("peer_id", "unknown")
            print(f"👋 {peer_id} left the notepad")
        
        def on_error(error):
            print(f"❌ Error: {error}")
        
        self.client.on('connected', on_connected)
        self.client.on('operation', on_operation)
        self.client.on('peer_join', on_peer_join)
        self.client.on('peer_leave', on_peer_leave)
        self.client.on('error', on_error)

    async def connect(self, backend_url: str) -> None:
        """Connect to the backend peer."""
        await self.client.connect(backend_url)
        
        # Wait for connection to stabilize
        await trio.sleep(1)
        
        # Initialize with demo content if document is empty
        if not self.client.get_document():
            await self._initialize_demo_content()

    async def _initialize_demo_content(self) -> None:
        """Initialize the notepad with demo content."""
        print("📝 Initializing with demo content...")
        
        full_content = "\n".join(self.demo_content)
        await self.client.update_document(full_content)
        
        print("✅ Demo content loaded!")

    async def insert_text_at_cursor(self, text: str) -> None:
        """Insert text at the current cursor position."""
        await self.client.insert_text(self.cursor_position, text)
        self.cursor_position += len(text)

    async def delete_at_cursor(self, length: int = 1) -> None:
        """Delete text at the current cursor position."""
        if self.cursor_position > 0:
            await self.client.delete_text(self.cursor_position - length, length)
            self.cursor_position = max(0, self.cursor_position - length)

    async def move_cursor(self, position: int) -> None:
        """Move cursor to the specified position."""
        document_length = len(self.client.get_document())
        self.cursor_position = max(0, min(position, document_length))
        
        # Send cursor position update
        await self.client.send_operation(self.client.sync_protocol.OperationType.UPDATE, {
            "cursor_position": self.cursor_position,
            "client_id": self.client_id
        })

    def display_document(self) -> None:
        """Display the current document with cursor position."""
        document = self.client.get_document()
        
        print("\n" + "=" * 60)
        print("📝 COLLABORATIVE NOTEPAD")
        print("=" * 60)
        
        if not document:
            print("(Empty document)")
        else:
            # Show document with cursor
            lines = document.split('\n')
            current_line = 0
            current_pos = 0
            
            for i, line in enumerate(lines):
                line_start = current_pos
                line_end = current_pos + len(line)
                
                if line_start <= self.cursor_position <= line_end:
                    # Cursor is on this line
                    cursor_in_line = self.cursor_position - line_start
                    display_line = line[:cursor_in_line] + "|" + line[cursor_in_line:]
                    print(f"{i+1:3d}: {display_line}")
                else:
                    print(f"{i+1:3d}: {line}")
                
                current_pos = line_end + 1  # +1 for newline
            
            # If cursor is at the end
            if self.cursor_position == len(document):
                print("     |")
        
        print("=" * 60)
        print(f"Cursor: {self.cursor_position} | Document length: {len(document)}")
        print(f"Connected peers: {len(self.client.get_connected_peers())}")
        print("=" * 60)

    async def interactive_mode(self) -> None:
        """Run interactive notepad mode."""
        print("\n🎮 Interactive Mode Commands:")
        print("  i <text>     - Insert text at cursor")
        print("  d [length]   - Delete text at cursor (default: 1)")
        print("  m <position> - Move cursor to position")
        print("  r            - Refresh display")
        print("  s            - Show stats")
        print("  q            - Quit")
        print("  h            - Show this help")
        print()
        
        while True:
            try:
                # Display current document
                self.display_document()
                
                # Get user input
                command = input("\n> ").strip()
                
                if not command:
                    continue
                
                parts = command.split(' ', 1)
                cmd = parts[0].lower()
                
                if cmd == 'q':
                    print("👋 Goodbye!")
                    break
                elif cmd == 'h':
                    print("\n🎮 Interactive Mode Commands:")
                    print("  i <text>     - Insert text at cursor")
                    print("  d [length]   - Delete text at cursor (default: 1)")
                    print("  m <position> - Move cursor to position")
                    print("  r            - Refresh display")
                    print("  s            - Show stats")
                    print("  q            - Quit")
                    print("  h            - Show this help")
                elif cmd == 'i' and len(parts) > 1:
                    text = parts[1]
                    await self.insert_text_at_cursor(text)
                elif cmd == 'd':
                    length = int(parts[1]) if len(parts) > 1 else 1
                    await self.delete_at_cursor(length)
                elif cmd == 'm' and len(parts) > 1:
                    try:
                        position = int(parts[1])
                        await self.move_cursor(position)
                    except ValueError:
                        print("❌ Invalid position. Please enter a number.")
                elif cmd == 'r':
                    pass  # Just refresh display
                elif cmd == 's':
                    stats = self.client.get_stats()
                    print(f"\n📊 Client Statistics:")
                    print(f"  Client ID: {stats['client_id']}")
                    print(f"  Connected: {stats['connected']}")
                    print(f"  Operations sent: {stats['operations_sent']}")
                    print(f"  Operations received: {stats['operations_received']}")
                    print(f"  Connected peers: {len(stats.get('connected_peers', []))}")
                    if stats.get('connected_at'):
                        uptime = time.time() - stats['connected_at']
                        print(f"  Uptime: {uptime:.1f} seconds")
                else:
                    print("❌ Unknown command. Type 'h' for help.")
                
                # Small delay to allow operations to process
                await trio.sleep(0.1)
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")

    async def demo_mode(self) -> None:
        """Run automated demo mode."""
        print("🎬 Starting automated demo...")
        
        # Wait for connection
        await trio.sleep(2)
        
        # Demo operations
        demo_operations = [
            ("insert", "Hello, "),
            ("insert", "World!"),
            ("insert", "\n\nThis is a demo of collaborative editing."),
            ("insert", "\nMultiple users can edit simultaneously."),
            ("insert", "\nChanges sync in real-time!"),
        ]
        
        for op_type, text in demo_operations:
            if op_type == "insert":
                await self.insert_text_at_cursor(text)
                await trio.sleep(1)
        
        # Show final result
        await trio.sleep(1)
        self.display_document()
        
        print("\n🎉 Demo completed!")
        print("💡 Try opening another client to see real-time collaboration")
        
        # Keep running to receive operations
        await trio.sleep_forever()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Collaborative Notepad Demo")
    parser.add_argument("--backend-url", required=True, help="Backend WebSocket URL")
    parser.add_argument("--client-id", help="Client ID (auto-generated if not provided)")
    parser.add_argument("--mode", choices=["interactive", "demo"], default="interactive",
                       help="Run mode: interactive or demo")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create notepad
    notepad = CollaborativeNotepad(args.client_id, args.debug)
    
    try:
        # Connect to backend
        await notepad.connect(args.backend_url)
        
        # Run in specified mode
        if args.mode == "interactive":
            await notepad.interactive_mode()
        else:
            await notepad.demo_mode()
            
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        await notepad.client.disconnect()


if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        print("\n✅ Clean exit completed.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
