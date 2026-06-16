import argparse

def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="py-ipfs-lite runner")
    parser.add_argument("--config", default="config.json", help="Path to JSON config file")
    
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Daemon command
    daemon_parser = subparsers.add_parser("daemon", help="Run the IPFS Lite daemon")
    daemon_parser.add_argument("--port", type=int, help="Port to listen on")
    daemon_parser.add_argument("--seed", type=str, help="Seed for deterministic peer ID")
    daemon_parser.add_argument("--offline", action="store_true", help="Run in offline mode")

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a file")
    add_parser.add_argument("file", type=str, help="File to add")
    add_parser.add_argument("--port", type=int, help="Port to listen on")
    add_parser.add_argument("--seed", type=str, help="Seed for deterministic peer ID")
    add_parser.add_argument("--chunker", type=str, help="Chunking algorithm (e.g., size-262144)")
    add_parser.add_argument("--hash-fun", type=str, help="Hash function (e.g., sha2-256)")
    add_parser.add_argument("--raw-leaves", action="store_true", help="Use raw leaves")
    add_parser.add_argument("--offline", action="store_true", help="Run in offline mode")

    # Get command
    get_parser = subparsers.add_parser("get", help="Get a file by CID")
    get_parser.add_argument("cid", type=str, help="CID to fetch")
    get_parser.add_argument("--provider", required=True, type=str, help="Provider multiaddress")
    get_parser.add_argument("--out", type=str, help="Output file path")
    get_parser.add_argument("--port", type=int, help="Port to listen on")
    get_parser.add_argument("--seed", type=str, help="Seed for deterministic peer ID")
    get_parser.add_argument("--offline", action="store_true", help="Run in offline mode")

    return parser
