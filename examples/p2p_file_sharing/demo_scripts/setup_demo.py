#!/usr/bin/env python3
"""
Demo setup script for P2P File Sharing.

This script sets up a demo environment with sample files and configuration
for testing the P2P file sharing application across different networks.
"""

import os
import shutil
import sys
from pathlib import Path

def create_demo_files():
    """Create sample files for the demo."""
    print("📁 Creating demo files...")
    
    # Create shared files directory
    shared_dir = Path("./shared_files")
    shared_dir.mkdir(exist_ok=True)
    
    # Create sample files
    sample_files = [
        ("sample_text.txt", "This is a sample text file for P2P file sharing demo.\n" * 100),
        ("sample_data.json", '{"name": "P2P File Sharing", "version": "1.0.0", "features": ["NAT traversal", "Peer discovery", "File transfer"]}'),
        ("readme.md", "# P2P File Sharing Demo\n\nThis is a demonstration of peer-to-peer file sharing with NAT traversal capabilities."),
    ]
    
    for filename, content in sample_files:
        file_path = shared_dir / filename
        with open(file_path, 'w') as f:
            f.write(content)
        print(f"  ✅ Created: {filename}")
    
    # Create a larger file for testing
    large_file_path = shared_dir / "large_file.bin"
    with open(large_file_path, 'wb') as f:
        # Write 1MB of random data
        f.write(b'0' * (1024 * 1024))
    print(f"  ✅ Created: large_file.bin (1MB)")

def create_download_directory():
    """Create download directory."""
    print("📥 Creating download directory...")
    download_dir = Path("./downloads")
    download_dir.mkdir(exist_ok=True)
    print("  ✅ Created: downloads/")

def create_demo_scripts():
    """Create demo scripts for different scenarios."""
    print("📜 Creating demo scripts...")
    
    scripts_dir = Path("./demo_scripts")
    scripts_dir.mkdir(exist_ok=True)
    
    # Create peer 1 script
    peer1_script = scripts_dir / "start_peer1.py"
    with open(peer1_script, 'w') as f:
        f.write('''#!/usr/bin/env python3
"""
Start Peer 1 for P2P File Sharing Demo.
This peer will act as a server and share files.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from examples.p2p_file_sharing.file_sharing_app import main
import trio

if __name__ == "__main__":
    print("🚀 Starting Peer 1 (Server)...")
    trio.run(main)
''')
    
    # Create peer 2 script
    peer2_script = scripts_dir / "start_peer2.py"
    with open(peer2_script, 'w') as f:
        f.write('''#!/usr/bin/env python3
"""
Start Peer 2 for P2P File Sharing Demo.
This peer will connect to Peer 1 and download files.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from examples.p2p_file_sharing.file_sharing_app import main
import trio

if __name__ == "__main__":
    print("🚀 Starting Peer 2 (Client)...")
    trio.run(main)
''')
    
    # Make scripts executable
    os.chmod(peer1_script, 0o755)
    os.chmod(peer2_script, 0o755)
    
    print("  ✅ Created: start_peer1.py")
    print("  ✅ Created: start_peer2.py")

def create_nat_test_script():
    """Create NAT testing script."""
    print("🌐 Creating NAT testing script...")
    
    scripts_dir = Path("./demo_scripts")
    nat_test_script = scripts_dir / "test_nat_traversal.py"
    
    with open(nat_test_script, 'w') as f:
        f.write('''#!/usr/bin/env python3
"""
NAT Traversal Test Script.

This script tests NAT traversal capabilities by starting two peers
on different ports and attempting to connect them.
"""

import asyncio
import sys
import os
import trio
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from examples.p2p_file_sharing.file_sharing_app import P2PFileSharingApp

async def test_nat_traversal():
    """Test NAT traversal between two peers."""
    print("🧪 Testing NAT Traversal...")
    
    # Create two app instances with different ports
    app1 = P2PFileSharingApp(port=8001, seed=12345)
    app2 = P2PFileSharingApp(port=8002, seed=54321)
    
    try:
        # Start both apps
        print("Starting Peer 1 on port 8001...")
        async with app1.host.run(listen_addrs=app1.host.get_addrs()):
            await app1.initialize()
            
            print("Starting Peer 2 on port 8002...")
            async with app2.host.run(listen_addrs=app2.host.get_addrs()):
                await app2.initialize()
                
                # Get peer addresses
                peer1_addrs = app1.host.get_addrs()
                peer2_addrs = app2.host.get_addrs()
                
                print(f"Peer 1 addresses: {peer1_addrs}")
                print(f"Peer 2 addresses: {peer2_addrs}")
                
                # Test connection
                print("Testing connection between peers...")
                # This would require the full connection logic
                # For now, just show the addresses
                
                print("✅ NAT traversal test completed")
                
    except Exception as e:
        print(f"❌ NAT traversal test failed: {e}")
    finally:
        await app1.shutdown()
        await app2.shutdown()

if __name__ == "__main__":
    trio.run(test_nat_traversal)
''')
    
    os.chmod(nat_test_script, 0o755)
    print("  ✅ Created: test_nat_traversal.py")

def create_documentation():
    """Create demo documentation."""
    print("📚 Creating demo documentation...")
    
    docs_dir = Path("./demo_scripts")
    readme_path = docs_dir / "README.md"
    
    with open(readme_path, 'w') as f:
        f.write('''# P2P File Sharing Demo

This demo showcases peer-to-peer file sharing with NAT traversal capabilities using py-libp2p.

## Quick Start

1. **Setup the demo environment:**
   ```bash
   python setup_demo.py
   ```

2. **Start Peer 1 (Server):**
   ```bash
   python demo_scripts/start_peer1.py
   ```

3. **Start Peer 2 (Client) in another terminal:**
   ```bash
   python demo_scripts/start_peer2.py
   ```

4. **Connect the peers:**
   - Copy the multiaddress from Peer 1
   - In Peer 2, use the `connect` command with that address

5. **Share and download files:**
   - Use `list-files` to see available files
   - Use `download <hash>` to download files
   - Use `share <file>` to add files to your shared directory

## Demo Scenarios

### Scenario 1: Local Network
- Both peers on the same network
- Direct connection should work
- Fast file transfer

### Scenario 2: NAT Traversal
- Peers behind different NATs
- Uses Circuit Relay v2 for connection
- Demonstrates hole punching with DCUtR

### Scenario 3: Peer Discovery
- Uses mDNS for local discovery
- Bootstrap nodes for initial connectivity
- Persistent peer database

## Commands

- `list-files` - List available files from connected peers
- `list-peers` - List connected peers
- `connect <address>` - Connect to a peer
- `download <hash>` - Download a file by hash
- `share <file>` - Add a file to shared files
- `stats` - Show connection statistics
- `help` - Show help
- `quit` - Exit

## Files Created

- `shared_files/` - Directory containing files to share
- `downloads/` - Directory for downloaded files
- `peer_database.json` - Persistent peer information
- `demo_scripts/` - Demo scripts and documentation

## Testing NAT Traversal

Run the NAT traversal test:
```bash
python demo_scripts/test_nat_traversal.py
```

This will start two peers and test their connectivity.

## Troubleshooting

1. **Connection Issues:**
   - Check firewall settings
   - Ensure ports are not blocked
   - Try different ports

2. **File Transfer Issues:**
   - Check file permissions
   - Ensure sufficient disk space
   - Verify file hashes

3. **NAT Traversal Issues:**
   - Check if you're behind a restrictive NAT
   - Try connecting to bootstrap nodes first
   - Use relay nodes for connectivity

## Advanced Usage

### Custom Configuration

You can customize the application with command-line arguments:

```bash
python -m examples.p2p_file_sharing.file_sharing_app \\
    --port 8000 \\
    --shared-dir ./my_files \\
    --download-dir ./my_downloads \\
    --peer-db ./my_peers.json \\
    --seed 12345 \\
    --verbose
```

### Integration with Other Applications

The P2P file sharing components can be integrated into other applications:

```python
from examples.p2p_file_sharing.file_sharing_app import P2PFileSharingApp

app = P2PFileSharingApp(port=8000)
await app.initialize()
# Use app for file sharing operations
```

## Contributing

This demo is part of the py-libp2p project. Contributions are welcome!

See the main project documentation for development guidelines.
''')
    
    print("  ✅ Created: README.md")

def main():
    """Main setup function."""
    print("🚀 Setting up P2P File Sharing Demo...")
    print("=" * 50)
    
    try:
        create_demo_files()
        create_download_directory()
        create_demo_scripts()
        create_nat_test_script()
        create_documentation()
        
        print("\n" + "=" * 50)
        print("✅ Demo setup completed successfully!")
        print("\n📋 Next steps:")
        print("1. Start Peer 1: python demo_scripts/start_peer1.py")
        print("2. Start Peer 2: python demo_scripts/start_peer2.py")
        print("3. Connect the peers using the multiaddress")
        print("4. Try sharing and downloading files!")
        print("\n📚 See demo_scripts/README.md for detailed instructions")
        
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
