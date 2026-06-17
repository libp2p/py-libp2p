import argparse
from py_ipfs_lite.config import CLIConfig, Config, AddParams


def get_parser() -> argparse.ArgumentParser:
    cli_defaults = CLIConfig()
    core_defaults = Config()
    add_defaults = AddParams()

    parser = argparse.ArgumentParser(description="py-ipfs-lite runner")
    parser.add_argument(
        "--debug",
        action="store_true",
        default=cli_defaults.debug,
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Daemon command
    daemon_parser = subparsers.add_parser("daemon", help="Run the IPFS Lite daemon")
    daemon_parser.add_argument(
        "--port", type=int, default=cli_defaults.port, help="Port to listen on"
    )
    daemon_parser.add_argument(
        "--api", action="store_true", help="Enable the HTTP API server"
    )
    daemon_parser.add_argument(
        "--api-host", type=str, default="127.0.0.1", help="API server host"
    )
    daemon_parser.add_argument(
        "--api-port", type=int, default=5001, help="API server port"
    )
    daemon_parser.add_argument(
        "--seed",
        type=str,
        default=cli_defaults.seed,
        help="Seed for deterministic peer ID",
    )
    daemon_parser.add_argument(
        "--offline",
        action="store_true",
        default=core_defaults.offline,
        help="Run in offline mode",
    )
    daemon_parser.add_argument(
        "--reprovide-interval",
        type=int,
        default=core_defaults.reprovide_interval_seconds,
        dest="reprovide_interval_seconds",
        help="Reprovide interval in seconds",
    )
    daemon_parser.add_argument(
        "--blockstore-type",
        type=str,
        default=core_defaults.blockstore_type,
        choices=["memory", "filesystem"],
        help="Type of blockstore to use (memory or filesystem)",
    )
    daemon_parser.add_argument(
        "--blockstore-path",
        type=str,
        default=core_defaults.blockstore_path,
        help="Path to filesystem blockstore (required if type is filesystem)",
    )

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a file")
    add_parser.add_argument("file", type=str, help="File to add")
    add_parser.add_argument(
        "--port", type=int, default=cli_defaults.port, help="Port to listen on"
    )
    add_parser.add_argument(
        "--seed",
        type=str,
        default=cli_defaults.seed,
        help="Seed for deterministic peer ID",
    )
    add_parser.add_argument(
        "--chunker",
        type=str,
        default=add_defaults.chunker,
        help="Chunking algorithm (e.g., size-262144)",
    )
    add_parser.add_argument(
        "--hash-fun",
        type=str,
        default=add_defaults.hash_fun,
        help="Hash function (e.g., sha2-256)",
    )
    # For boolean with True default, we use action="store_false" but user can override, wait, argparse BooleanOptionalAction is Python 3.9+.
    # For simplicity, store_true is standard but AddParams has raw_leaves default to True.
    # We can do action=argparse.BooleanOptionalAction in python 3.9+ to allow --raw-leaves / --no-raw-leaves.
    add_parser.add_argument(
        "--raw-leaves",
        action=argparse.BooleanOptionalAction,
        default=add_defaults.raw_leaves,
        help="Use raw leaves",
    )
    add_parser.add_argument(
        "--offline",
        action="store_true",
        default=core_defaults.offline,
        help="Run in offline mode",
    )
    add_parser.add_argument(
        "--blockstore-type",
        type=str,
        default=core_defaults.blockstore_type,
        choices=["memory", "filesystem"],
        help="Type of blockstore to use (memory or filesystem)",
    )
    add_parser.add_argument(
        "--blockstore-path",
        type=str,
        default=core_defaults.blockstore_path,
        help="Path to filesystem blockstore (required if type is filesystem)",
    )

    # Get command
    get_parser = subparsers.add_parser("get", help="Get a file by CID")
    get_parser.add_argument("cid", type=str, help="CID to fetch")
    get_parser.add_argument(
        "--provider",
        required=False,
        type=str,
        default=None,
        help="Provider multiaddress",
    )
    get_parser.add_argument("--out", type=str, default=None, help="Output file path")
    get_parser.add_argument(
        "--port", type=int, default=cli_defaults.port, help="Port to listen on"
    )
    get_parser.add_argument(
        "--seed",
        type=str,
        default=cli_defaults.seed,
        help="Seed for deterministic peer ID",
    )
    get_parser.add_argument(
        "--offline",
        action="store_true",
        default=core_defaults.offline,
        help="Run in offline mode",
    )
    get_parser.add_argument(
        "--blockstore-type",
        type=str,
        default=core_defaults.blockstore_type,
        choices=["memory", "filesystem"],
        help="Type of blockstore to use (memory or filesystem)",
    )
    get_parser.add_argument(
        "--blockstore-path",
        type=str,
        default=core_defaults.blockstore_path,
        help="Path to filesystem blockstore (required if type is filesystem)",
    )

    return parser
