"""
Robust Example: Cross-platform path handling with libp2p.utils.paths

This script demonstrates production-ready best practices for file and directory operations using
py-libp2p path utilities. These utilities ensure your code works on Windows, macOS, and Linux.
"""

import logging
from typing import Optional
from libp2p.utils.paths import (
    join_paths,
    get_temp_dir,
    get_script_dir,
    create_temp_file,
    ensure_dir_exists,
    resolve_relative_path,
)
from pathlib import Path


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for the example."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def write_and_read_temp_file(temp_file: Path) -> None:
    """Write to and read from a temporary file, with error handling."""
    try:
        with temp_file.open("w", encoding="utf-8") as f:
            f.write("py-libp2p path utilities demo\n")
        logging.info(f"Wrote to temp file: {temp_file}")
        with temp_file.open("r", encoding="utf-8") as f:
            content = f.read()
        logging.info(f"Read from temp file: {content.strip()}")
    except Exception as e:
        logging.error(f"Error handling temp file: {e}")


def main() -> None:
    """Run robust path handling demo."""
    setup_logging()

    # Join paths in a cross-platform way
    data_dir: Path = join_paths(get_temp_dir(), "py-libp2p-demo", "data")
    try:
        ensure_dir_exists(data_dir)
        logging.info(f"Data directory ensured: {data_dir}")
    except Exception as e:
        logging.error(f"Failed to create data directory: {e}")
        return

    # Get the directory of this script
    try:
        script_dir: Path = get_script_dir(__file__)
        logging.info(f"Script directory: {script_dir}")
    except Exception as e:
        logging.error(f"Could not determine script directory: {e}")
        return

    # Create a temporary file and demonstrate file I/O
    temp_file: Optional[Path] = None
    try:
        temp_file = create_temp_file(prefix="demo_")
        logging.info(f"Created temp file: {temp_file}")
        write_and_read_temp_file(temp_file)
    except Exception as e:
        logging.error(f"Failed to create or use temp file: {e}")

    # Resolve a relative path from the script directory
    try:
        rel_path: Path = resolve_relative_path(script_dir, "../README.md")
        if rel_path.exists():
            logging.info(f"Resolved README.md path: {rel_path}")
        else:
            logging.warning(f"README.md not found at resolved path: {rel_path}")
    except Exception as e:
        logging.error(f"Failed to resolve relative path: {e}")

    # Clean up temp file (optional, safe for production)
    if temp_file:
        try:
            temp_file.unlink(missing_ok=True)
            logging.info(f"Cleaned up temp file: {temp_file}")
        except Exception as e:
            logging.warning(f"Could not remove temp file: {e}")

if __name__ == "__main__":
    main()
