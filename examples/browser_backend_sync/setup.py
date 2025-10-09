#!/usr/bin/env python3
"""
Setup script for Browser-to-Backend P2P Sync demo.

This script helps set up the environment and install dependencies
for the browser-to-backend P2P sync demonstration.
"""

import os
import sys
import subprocess
import argparse
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_command(command, description, check=True):
    """Run a shell command with logging."""
    logger.info(f"Running: {description}")
    logger.debug(f"Command: {command}")
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=check,
            capture_output=True,
            text=True
        )
        
        if result.stdout:
            logger.debug(f"Output: {result.stdout}")
        
        if result.stderr:
            logger.debug(f"Error output: {result.stderr}")
        
        return result.returncode == 0
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e}")
        if e.stdout:
            logger.error(f"Output: {e.stdout}")
        if e.stderr:
            logger.error(f"Error: {e.stderr}")
        return False


def check_python_version():
    """Check if Python version is compatible."""
    logger.info("Checking Python version...")
    
    if sys.version_info < (3, 8):
        logger.error("Python 3.8 or higher is required")
        return False
    
    logger.info(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} ✓")
    return True


def install_dependencies():
    """Install required dependencies."""
    logger.info("Installing dependencies...")
    
    dependencies = [
        "trio",
        "websockets",
        "multiaddr",
        "pycryptodome",
        "protobuf",
        "zeroconf"
    ]
    
    for dep in dependencies:
        logger.info(f"Installing {dep}...")
        if not run_command(f"pip install {dep}", f"Install {dep}"):
            logger.warning(f"Failed to install {dep}, trying with --user flag")
            run_command(f"pip install --user {dep}", f"Install {dep} with --user")
    
    return True


def create_directories():
    """Create necessary directories."""
    logger.info("Creating directories...")
    
    directories = [
        "logs",
        "data",
        "temp"
    ]
    
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
        logger.info(f"Created directory: {directory}")
    
    return True


def create_config_file():
    """Create a default configuration file."""
    logger.info("Creating configuration file...")
    
    config_content = """# Browser-to-Backend P2P Sync Configuration

[backend]
port = 8000
websocket_port = 8001
enable_mdns = true
debug = false

[client]
default_backend_url = "ws://localhost:8001"
auto_connect = false
heartbeat_interval = 10

[logging]
level = "INFO"
file = "logs/sync.log"
max_size = "10MB"
backup_count = 5

[security]
enable_noise = true
enable_plaintext = false
"""
    
    config_path = Path("config.ini")
    if not config_path.exists():
        config_path.write_text(config_content)
        logger.info("Created config.ini")
    else:
        logger.info("config.ini already exists")
    
    return True


def create_startup_scripts():
    """Create startup scripts for easy launching."""
    logger.info("Creating startup scripts...")
    
    # Backend startup script
    backend_script = """#!/bin/bash
# Backend Peer Startup Script

echo "🚀 Starting Backend Peer for Browser-to-Backend P2P Sync"
echo "=================================================="

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed or not in PATH"
    exit 1
fi

# Check if we're in the right directory
if [ ! -f "backend_peer.py" ]; then
    echo "❌ backend_peer.py not found. Please run this script from the browser_backend_sync directory"
    exit 1
fi

# Start the backend peer
echo "📍 Starting backend peer on port 8000..."
echo "🌐 WebSocket server will be available on port 8001"
echo "📝 Open browser.html in your browser to connect"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python3 backend_peer.py --port 8000 --debug
"""
    
    backend_path = Path("start_backend.sh")
    backend_path.write_text(backend_script)
    backend_path.chmod(0o755)
    logger.info("Created start_backend.sh")
    
    # Client startup script
    client_script = """#!/bin/bash
# Browser Client Startup Script

echo "🌐 Starting Browser Client for P2P Sync"
echo "======================================="

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed or not in PATH"
    exit 1
fi

# Check if we're in the right directory
if [ ! -f "browser_client.py" ]; then
    echo "❌ browser_client.py not found. Please run this script from the browser_backend_sync directory"
    exit 1
fi

# Get client ID from user
read -p "Enter client ID (or press Enter for auto-generated): " CLIENT_ID

# Start the client
echo "🔗 Connecting to backend peer..."
echo ""

if [ -z "$CLIENT_ID" ]; then
    python3 browser_client.py --backend-url ws://localhost:8001 --debug
else
    python3 browser_client.py --backend-url ws://localhost:8001 --client-id "$CLIENT_ID" --debug
fi
"""
    
    client_path = Path("start_client.sh")
    client_path.write_text(client_script)
    client_path.chmod(0o755)
    logger.info("Created start_client.sh")
    
    # Demo startup script
    demo_script = """#!/bin/bash
# Demo Applications Startup Script

echo "🎬 Browser-to-Backend P2P Sync Demo"
echo "==================================="

echo "Available demos:"
echo "1. Collaborative Notepad (Interactive)"
echo "2. Collaborative Notepad (Automated)"
echo "3. Real-time Whiteboard (Interactive)"
echo "4. Real-time Whiteboard (Automated)"
echo "5. Open Browser Client"
echo ""

read -p "Select demo (1-5): " CHOICE

case $CHOICE in
    1)
        echo "📝 Starting Collaborative Notepad (Interactive Mode)"
        python3 notepad_demo.py --backend-url ws://localhost:8001 --mode interactive --debug
        ;;
    2)
        echo "📝 Starting Collaborative Notepad (Demo Mode)"
        python3 notepad_demo.py --backend-url ws://localhost:8001 --mode demo --debug
        ;;
    3)
        echo "🎨 Starting Real-time Whiteboard (Interactive Mode)"
        python3 whiteboard_demo.py --backend-url ws://localhost:8001 --mode interactive --debug
        ;;
    4)
        echo "🎨 Starting Real-time Whiteboard (Demo Mode)"
        python3 whiteboard_demo.py --backend-url ws://localhost:8001 --mode demo --debug
        ;;
    5)
        echo "🌐 Opening Browser Client"
        if command -v xdg-open &> /dev/null; then
            xdg-open browser.html
        elif command -v open &> /dev/null; then
            open browser.html
        else
            echo "Please open browser.html in your web browser"
        fi
        ;;
    *)
        echo "❌ Invalid choice"
        exit 1
        ;;
esac
"""
    
    demo_path = Path("start_demo.sh")
    demo_path.write_text(demo_script)
    demo_path.chmod(0o755)
    logger.info("Created start_demo.sh")
    
    return True


def create_readme():
    """Create a comprehensive README for the setup."""
    logger.info("Creating setup README...")
    
    readme_content = """# Browser-to-Backend P2P Sync - Setup Complete! 🎉

## Quick Start

### 1. Start the Backend Peer
```bash
./start_backend.sh
```
This will start the backend peer on port 8000 with WebSocket support on port 8001.

### 2. Connect Clients

#### Option A: Python Clients
```bash
./start_client.sh
```

#### Option B: Browser Client
```bash
./start_demo.sh
# Select option 5 to open browser.html
```

#### Option C: Demo Applications
```bash
./start_demo.sh
# Select from available demos
```

## Available Demos

1. **Collaborative Notepad** - Real-time text editing
2. **Real-time Whiteboard** - Collaborative drawing and annotation
3. **Browser Client** - Web-based interface

## Manual Commands

### Backend Peer
```bash
python3 backend_peer.py --port 8000 --debug
```

### Python Client
```bash
python3 browser_client.py --backend-url ws://localhost:8001 --client-id myclient --debug
```

### Notepad Demo
```bash
python3 notepad_demo.py --backend-url ws://localhost:8001 --mode interactive --debug
```

### Whiteboard Demo
```bash
python3 whiteboard_demo.py --backend-url ws://localhost:8001 --mode interactive --debug
```

## Browser Client

Open `browser.html` in your web browser and connect to `ws://localhost:8001`.

## Configuration

Edit `config.ini` to customize settings:
- Backend ports
- Logging levels
- Security options
- Client defaults

## Troubleshooting

### Common Issues

1. **Port already in use**: Change the port in the startup command
2. **Connection refused**: Make sure the backend peer is running
3. **WebSocket connection failed**: Check firewall settings

### Debug Mode

Add `--debug` flag to any command for verbose logging.

### Logs

Check the `logs/` directory for detailed logs.

## Architecture

```
Browser Client (WebSocket) ←→ Backend Peer (libp2p) ←→ Other Peers
```

The backend peer acts as a bridge between browser clients and the libp2p network,
providing NAT traversal and peer discovery capabilities.

## Features Demonstrated

- ✅ Real-time synchronization
- ✅ NAT traversal
- ✅ Peer discovery
- ✅ Conflict resolution
- ✅ Browser compatibility
- ✅ Multiple transport protocols
- ✅ Security with Noise protocol

## Next Steps

1. Try connecting multiple clients
2. Test real-time collaboration
3. Explore the sync protocol
4. Customize the demos
5. Build your own applications!

Happy coding! 🚀
"""
    
    readme_path = Path("SETUP_README.md")
    readme_path.write_text(readme_content)
    logger.info("Created SETUP_README.md")
    
    return True


def main():
    """Main setup function."""
    parser = argparse.ArgumentParser(description="Setup Browser-to-Backend P2P Sync")
    parser.add_argument("--skip-deps", action="store_true", help="Skip dependency installation")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("🚀 Setting up Browser-to-Backend P2P Sync")
    logger.info("=" * 50)
    
    # Check Python version
    if not check_python_version():
        sys.exit(1)
    
    # Install dependencies
    if not args.skip_deps:
        if not install_dependencies():
            logger.warning("Some dependencies may not have installed correctly")
    
    # Create directories
    if not create_directories():
        logger.error("Failed to create directories")
        sys.exit(1)
    
    # Create configuration
    if not create_config_file():
        logger.error("Failed to create configuration file")
        sys.exit(1)
    
    # Create startup scripts
    if not create_startup_scripts():
        logger.error("Failed to create startup scripts")
        sys.exit(1)
    
    # Create README
    if not create_readme():
        logger.error("Failed to create README")
        sys.exit(1)
    
    logger.info("=" * 50)
    logger.info("✅ Setup completed successfully!")
    logger.info("")
    logger.info("Next steps:")
    logger.info("1. Start the backend: ./start_backend.sh")
    logger.info("2. Connect clients: ./start_demo.sh")
    logger.info("3. Read SETUP_README.md for detailed instructions")
    logger.info("")
    logger.info("Happy coding! 🚀")


if __name__ == "__main__":
    main()
