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
    daemon_parser.add_argument("--port", type=int, default=cli_defaults.port, help="Port to listen on")
    daemon_parser.add_argument("--api", action="store_true", help="Enable the HTTP API server")
    daemon_parser.add_argument("--api-host", type=str, default="127.0.0.1", help="API server host")
    daemon_parser.add_argument("--api-port", type=int, default=5001, help="API server port")
    daemon_parser.add_argument("--seed", type=str, default=cli_defaults.seed, help="Seed for deterministic peer ID")
    daemon_parser.add_argument("--offline", action="store_true", default=core_defaults.offline, help="Run in offline mode")
    daemon_parser.add_argument("--reprovide-interval", type=int, default=core_defaults.reprovide_interval_seconds, dest="reprovide_interval_seconds", help="Reprovide interval in seconds")
    daemon_parser.add_argument("--blockstore-type", type=str, default=core_defaults.blockstore_type, choices=["memory", "filesystem"])
    daemon_parser.add_argument("--blockstore-path", type=str, default=core_defaults.blockstore_path)
    daemon_parser.add_argument("--no-ipni", action="store_false", dest="use_ipni", default=core_defaults.use_ipni, help="Disable IPNI HTTP delegated routing")
    daemon_parser.add_argument("--ipni-endpoint", type=str, default=core_defaults.ipni_endpoint, help="IPNI endpoint URL")

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a file")
    add_parser.add_argument("file", type=str, help="File to add")
    add_parser.add_argument("--port", type=int, default=cli_defaults.port, help="Port to listen on")
    add_parser.add_argument("--seed", type=str, default=cli_defaults.seed, help="Seed for deterministic peer ID")
    add_parser.add_argument("--chunker", type=str, default=add_defaults.chunker, help="Chunking algorithm (e.g., size-262144)")
    add_parser.add_argument("--hash-fun", type=str, default=add_defaults.hash_fun, help="Hash function (e.g., sha2-256)")
    add_parser.add_argument("--raw-leaves", action=argparse.BooleanOptionalAction, default=add_defaults.raw_leaves, help="Use raw leaves")
    add_parser.add_argument("--offline", action="store_true", default=core_defaults.offline, help="Run in offline mode")
    add_parser.add_argument("--blockstore-type", type=str, default=core_defaults.blockstore_type, choices=["memory", "filesystem"])
    add_parser.add_argument("--blockstore-path", type=str, default=core_defaults.blockstore_path)
    add_parser.add_argument("--no-ipni", action="store_false", dest="use_ipni", default=core_defaults.use_ipni, help="Disable IPNI HTTP delegated routing")
    add_parser.add_argument("--ipni-endpoint", type=str, default=core_defaults.ipni_endpoint, help="IPNI endpoint URL")

    # Get command
    get_parser = subparsers.add_parser("get", help="Get a file by CID")
    get_parser.add_argument("cid", type=str, help="CID to fetch")
    get_parser.add_argument("--provider", required=False, type=str, default=None, help="Provider multiaddress")
    get_parser.add_argument("--out", type=str, default=None, help="Output file path")
    get_parser.add_argument("--port", type=int, default=cli_defaults.port, help="Port to listen on")
    get_parser.add_argument("--seed", type=str, default=cli_defaults.seed, help="Seed for deterministic peer ID")
    get_parser.add_argument("--offline", action="store_true", default=core_defaults.offline, help="Run in offline mode")
    get_parser.add_argument("--blockstore-type", type=str, default=core_defaults.blockstore_type, choices=["memory", "filesystem"])
    get_parser.add_argument("--blockstore-path", type=str, default=core_defaults.blockstore_path)
    get_parser.add_argument("--no-ipni", action="store_false", dest="use_ipni", default=core_defaults.use_ipni, help="Disable IPNI HTTP delegated routing")
    get_parser.add_argument("--ipni-endpoint", type=str, default=core_defaults.ipni_endpoint, help="IPNI endpoint URL")

    # dag-export command
    dag_export_parser = subparsers.add_parser("dag-export", help="Export a DAG to a CAR file")
    dag_export_parser.add_argument("cid", type=str, help="CID to export")
    dag_export_parser.add_argument("out", type=str, help="Output CAR file path")
    dag_export_parser.add_argument("--port", type=int, default=cli_defaults.port, help="Port to listen on")
    dag_export_parser.add_argument("--seed", type=str, default=cli_defaults.seed, help="Seed for deterministic peer ID")
    dag_export_parser.add_argument("--offline", action="store_true", default=core_defaults.offline, help="Run in offline mode")
    dag_export_parser.add_argument("--blockstore-type", type=str, default=core_defaults.blockstore_type, choices=["memory", "filesystem"])
    dag_export_parser.add_argument("--blockstore-path", type=str, default=core_defaults.blockstore_path)
    dag_export_parser.add_argument("--no-ipni", action="store_false", dest="use_ipni", default=core_defaults.use_ipni, help="Disable IPNI HTTP delegated routing")
    dag_export_parser.add_argument("--ipni-endpoint", type=str, default=core_defaults.ipni_endpoint, help="IPNI endpoint URL")

    # dag-import command
    dag_import_parser = subparsers.add_parser("dag-import", help="Import a CAR file into the blockstore")
    dag_import_parser.add_argument("file", type=str, help="CAR file path to import")
    dag_import_parser.add_argument("--port", type=int, default=cli_defaults.port, help="Port to listen on")
    dag_import_parser.add_argument("--seed", type=str, default=cli_defaults.seed, help="Seed for deterministic peer ID")
    dag_import_parser.add_argument("--offline", action="store_true", default=core_defaults.offline, help="Run in offline mode")
    dag_import_parser.add_argument("--blockstore-type", type=str, default=core_defaults.blockstore_type, choices=["memory", "filesystem"])
    dag_import_parser.add_argument("--blockstore-path", type=str, default=core_defaults.blockstore_path)
    dag_import_parser.add_argument("--no-ipni", action="store_false", dest="use_ipni", default=core_defaults.use_ipni, help="Disable IPNI HTTP delegated routing")
    dag_import_parser.add_argument("--ipni-endpoint", type=str, default=core_defaults.ipni_endpoint, help="IPNI endpoint URL")

    return parser
