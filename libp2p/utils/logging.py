import atexit
from datetime import (
    datetime,
)
import logging
import logging.handlers
import os
from pathlib import (
    Path,
)
import queue
import sys
import threading
from typing import (
    Any,
)

# Create a log queue
log_queue: "queue.Queue[Any]" = queue.Queue()

# Store the current listener to stop it on exit
_current_listener: logging.handlers.QueueListener | None = None

# Event to track when the listener is ready
_listener_ready = threading.Event()

# Default format for log messages
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _parse_debug_modules(debug_str: str) -> dict[str, int]:
    """
    Parse the LIBP2P_DEBUG environment variable to determine module-specific log levels.

    Format examples:
    - "DEBUG"  # All modules at DEBUG level
    - "libp2p.identity.identify:DEBUG"  # Only identify module at DEBUG
    - "identity.identify:DEBUG"  # Same as above, libp2p prefix is optional
    - "libp2p.identity:DEBUG,libp2p.transport:INFO"  # Multiple modules
    """
    module_levels: dict[str, int] = {}

    # Handle empty or whitespace-only string
    if not debug_str or debug_str.isspace():
        return module_levels

    # If it's a plain log level without any colons, apply to all
    if ":" not in debug_str and debug_str.upper() in logging._nameToLevel:
        return {"": getattr(logging, debug_str.upper())}

    # Handle module-specific levels
    for part in debug_str.split(","):
        if ":" not in part:
            continue

        module, level = part.split(":")
        level = level.upper()

        if level not in logging._nameToLevel:
            continue

        # Handle module name
        module = module.strip()
        # Remove libp2p prefix if present, it will be added back when creating logger
        module = module.replace("libp2p.", "")
        # Convert any remaining dots to ensure proper format
        module = module.replace("/", ".").strip(".")

        module_levels[module] = getattr(logging, level)

    return module_levels


def setup_logging() -> None:
    """
    Set up logging configuration based on environment variables.

    Environment Variables:
        LIBP2P_DEBUG
            Controls logging levels. Examples:
            - "DEBUG" (all modules at DEBUG level)
            - "libp2p.identity.identify:DEBUG" (only identify module at DEBUG)
            - "identity.identify:DEBUG" (same as above, libp2p prefix optional)
            - "libp2p.identity:DEBUG,libp2p.transport:INFO" (multiple modules)

        LIBP2P_DEBUG_FILE
            If set, specifies the file path for log output. When this variable is set,
            logs will only be written to the specified file. If not set, logs will be
            written to both a default file (in the system's temp directory) and to
            stderr (console output).

    The logging system uses Python's native hierarchical logging:
        - Loggers are organized in a hierarchy using dots
          (e.g., libp2p.identity.identify)
        - Child loggers inherit their parent's level unless explicitly set
        - The root libp2p logger controls the default level
    """
    global _current_listener, _listener_ready

    # Reset the event
    _listener_ready.clear()

    # Stop existing listener if any
    if _current_listener is not None:
        _current_listener.stop()
        _current_listener = None

    # Get the log level from environment variable
    debug_str = os.environ.get("LIBP2P_DEBUG", "")

    if not debug_str:
        # If LIBP2P_DEBUG is not set, disable logging
        root_logger = logging.getLogger("libp2p")
        root_logger.handlers.clear()
        root_logger.setLevel(logging.WARNING)
        root_logger.propagate = False
        _listener_ready.set()  # Signal that we're done
        return

    # Parse module-specific levels
    module_levels = _parse_debug_modules(debug_str)

    # If no valid levels specified, default to WARNING
    if not module_levels:
        root_logger = logging.getLogger("libp2p")
        root_logger.handlers.clear()
        root_logger.setLevel(logging.WARNING)
        root_logger.propagate = False
        _listener_ready.set()  # Signal that we're done
        return

    # Create formatter
    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

    # Configure handlers
    handlers: list[logging.StreamHandler[Any] | logging.FileHandler] = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    # File handler (if configured)
    log_file = os.environ.get("LIBP2P_DEBUG_FILE")

    if log_file:
        # Ensure the directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        # Default log file with timestamp and unique identifier
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        unique_id = os.urandom(4).hex()  # Add a unique identifier to prevent collisions
        if os.name == "nt":  # Windows
            log_file = f"C:\\Windows\\Temp\\py-libp2p_{timestamp}_{unique_id}.log"
        else:  # Unix-like
            log_file = f"/tmp/py-libp2p_{timestamp}_{unique_id}.log"

        # Print the log file path so users know where to find it
        print(f"Logging to: {log_file}", file=sys.stderr)

    try:
        file_handler = logging.FileHandler(
            log_file, mode="w"
        )  # Use 'w' mode to clear file
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except Exception as e:
        print(f"Error creating file handler: {e}", file=sys.stderr)
        raise

    # Create a QueueHandler and QueueListener
    queue_handler = logging.handlers.QueueHandler(log_queue)

    # Configure root logger for libp2p
    root_logger = logging.getLogger("libp2p")
    root_logger.handlers.clear()
    root_logger.addHandler(queue_handler)
    root_logger.propagate = False

    # Set default level based on configuration
    if "" in module_levels:
        # Global level specified
        root_logger.setLevel(module_levels[""])
    else:
        # Default to INFO for module-specific logging
        root_logger.setLevel(logging.INFO)

    # Configure module-specific levels
    for module, level in module_levels.items():
        if module:  # Skip the default "" key
            logger = logging.getLogger(f"libp2p.{module}")
            logger.handlers.clear()
            logger.addHandler(queue_handler)
            logger.setLevel(level)
            logger.propagate = False  # Prevent message duplication

    # Start the listener AFTER configuring all loggers
    _current_listener = logging.handlers.QueueListener(
        log_queue, *handlers, respect_handler_level=True
    )
    _current_listener.start()

    # Signal that the listener is ready
    _listener_ready.set()


# Register cleanup function
@atexit.register
def cleanup_logging() -> None:
    """Clean up logging resources on exit."""
    global _current_listener
    if _current_listener is not None:
        _current_listener.stop()
        _current_listener = None
