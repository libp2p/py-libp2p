import argparse

from py_ipfs_lite.config import AddParams, CLIConfig, Config


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
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to a file to store logs instead of stdout",
    )

    # Common arguments parser
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--port", type=int, default=cli_defaults.port, help="Port to listen on"
    )
    common_parser.add_argument(
        "--seed",
        type=str,
        default=cli_defaults.seed,
        help="Seed for deterministic peer ID",
    )
    common_parser.add_argument(
        "--offline",
        action="store_true",
        default=core_defaults.offline,
        help="Run in offline mode",
    )
    common_parser.add_argument(
        "--blockstore-type",
        type=str,
        default=getattr(
            core_defaults.blockstore_type, "value", core_defaults.blockstore_type
        ),
        choices=["memory", "filesystem"],
    )
    common_parser.add_argument(
        "--blockstore-path", type=str, default=core_defaults.blockstore_path
    )
    common_parser.add_argument(
        "--ipni",
        action=argparse.BooleanOptionalAction,
        dest="use_ipni",
        default=core_defaults.use_ipni,
        help="Enable/Disable IPNI HTTP delegated routing",
    )
    common_parser.add_argument(
        "--ipni-endpoint",
        type=str,
        default=core_defaults.ipni_endpoint,
        help="IPNI endpoint URL",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Daemon command
    daemon_parser = subparsers.add_parser(
        "daemon", help="Run the IPFS Lite daemon", parents=[common_parser]
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
        "--reprovide-interval",
        type=int,
        default=core_defaults.reprovide_interval_seconds,
        dest="reprovide_interval_seconds",
        help="Reprovide interval in seconds",
    )

    # Add command
    add_parser = subparsers.add_parser(
        "add", help="Add a file", parents=[common_parser]
    )
    add_parser.add_argument("file", type=str, help="File to add")
    add_parser.add_argument(
        "--chunker",
        type=str,
        default=add_defaults.chunker,
        help="Chunking algorithm (e.g., size-262144)",
    )
    # Get command
    get_parser = subparsers.add_parser(
        "get", help="Get a file by CID", parents=[common_parser]
    )
    get_parser.add_argument("cid", type=str, help="CID to fetch")
    get_parser.add_argument(
        "--provider",
        required=False,
        type=str,
        default=None,
        help="Provider multiaddress",
    )
    get_parser.add_argument("--out", type=str, default=None, help="Output file path")

    # dag-export command
    dag_export_parser = subparsers.add_parser(
        "dag-export", help="Export a DAG to a CAR file", parents=[common_parser]
    )
    dag_export_parser.add_argument("cid", type=str, help="CID to export")
    dag_export_parser.add_argument("out", type=str, help="Output CAR file path")

    # dag-import command
    dag_import_parser = subparsers.add_parser(
        "dag-import",
        help="Import a CAR file into the blockstore",
        parents=[common_parser],
    )
    dag_import_parser.add_argument("file", type=str, help="CAR file path to import")

    return parser
