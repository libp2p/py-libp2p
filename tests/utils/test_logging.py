import logging
import logging.handlers
import os
from pathlib import (
    Path,
)
import queue
import tempfile
import threading
from unittest.mock import (
    patch,
)

import pytest
import trio

from libp2p.utils.logging import (
    _current_listener,
    _listener_ready,
    log_queue,
    setup_logging,
)


def _reset_logging():
    """Reset all logging state."""
    global _current_listener, _listener_ready

    # Stop existing listener if any
    if _current_listener is not None:
        _current_listener.stop()
        _current_listener = None

    # Reset the event
    _listener_ready = threading.Event()

    # Reset the root logger
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)

    # Clear all loggers
    for name in list(logging.Logger.manager.loggerDict.keys()):
        if name.startswith("libp2p"):
            del logging.Logger.manager.loggerDict[name]  # Remove logger from registry

    # Reset libp2p logger
    logger = logging.getLogger("libp2p")
    logger.handlers.clear()
    logger.propagate = False  # Don't propagate to Python's root logger
    logger.setLevel(logging.WARNING)  # Default level

    # Clear the log queue
    while not log_queue.empty():
        try:
            log_queue.get_nowait()
        except queue.Empty:
            break


@pytest.fixture(autouse=True)
def clean_env():
    """Remove relevant environment variables before each test."""
    # Save original environment
    original_env = {}
    for var in ["LIBP2P_DEBUG", "LIBP2P_DEBUG_FILE"]:
        if var in os.environ:
            original_env[var] = os.environ[var]
            del os.environ[var]

    # Reset logging state
    _reset_logging()

    yield

    # Reset logging state again
    _reset_logging()

    # Restore original environment
    for var, value in original_env.items():
        os.environ[var] = value


@pytest.fixture
def clean_logger():
    """Reset the libp2p logger before each test."""
    # Reset logging state
    _reset_logging()

    yield logging.getLogger("libp2p")

    # Reset logging state again
    _reset_logging()


def test_logging_disabled(clean_env):
    """Test that logging is disabled when LIBP2P_DEBUG is not set."""
    setup_logging()
    logger = logging.getLogger("libp2p")
    assert logger.level == logging.WARNING
    assert not logger.handlers


def test_logging_with_debug_env(clean_env):
    """Test that logging is properly configured when LIBP2P_DEBUG is set."""
    os.environ["LIBP2P_DEBUG"] = "DEBUG"
    setup_logging()
    logger = logging.getLogger("libp2p")

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1  # Should have the QueueHandler

    # The handler should be a QueueHandler
    assert isinstance(logger.handlers[0], logging.handlers.QueueHandler)


def test_module_specific_logging(clean_env):
    """Test module-specific logging levels."""
    os.environ["LIBP2P_DEBUG"] = "identity.identify:DEBUG,transport:INFO"
    setup_logging()

    # Check root logger (should be at INFO by default)
    root_logger = logging.getLogger("libp2p")
    assert root_logger.level == logging.INFO

    # Check identify module (should be at DEBUG)
    identify_logger = logging.getLogger("libp2p.identity.identify")
    assert identify_logger.level == logging.DEBUG

    # Check transport module (should be at INFO)
    transport_logger = logging.getLogger("libp2p.transport")
    assert transport_logger.level == logging.INFO

    # Check unspecified module (should inherit from root)
    other_logger = logging.getLogger("libp2p.other")
    assert other_logger.getEffectiveLevel() == logging.INFO


def test_global_logging_level(clean_env):
    """Test setting a global logging level."""
    os.environ["LIBP2P_DEBUG"] = "DEBUG"
    setup_logging()

    # Root logger should be at DEBUG
    root_logger = logging.getLogger("libp2p")
    assert root_logger.level == logging.DEBUG

    # All modules should inherit the DEBUG level
    for module in ["identity", "transport", "other"]:
        logger = logging.getLogger(f"libp2p.{module}")
        assert logger.getEffectiveLevel() == logging.DEBUG


@pytest.mark.trio
async def test_custom_log_file(clean_env):
    """Test logging to a custom file path."""
    with tempfile.TemporaryDirectory() as temp_dir:
        log_file = Path(temp_dir) / "test.log"
        os.environ["LIBP2P_DEBUG"] = "INFO"
        os.environ["LIBP2P_DEBUG_FILE"] = str(log_file)

        setup_logging()

        # Wait for the listener to be ready
        _listener_ready.wait(timeout=1)

        logger = logging.getLogger("libp2p")
        logger.info("Test message")

        # Give the listener time to process the message
        await trio.sleep(0.1)

        # Stop the listener to ensure all messages are written
        if _current_listener is not None:
            _current_listener.stop()

        # Check if the file exists and contains our message
        assert log_file.exists()
        content = log_file.read_text()
        assert "Test message" in content


@pytest.mark.trio
async def test_default_log_file(clean_env):
    """Test logging to the default file path."""
    os.environ["LIBP2P_DEBUG"] = "INFO"

    with patch("libp2p.utils.logging.datetime") as mock_datetime:
        # Mock the timestamp to have a predictable filename
        mock_datetime.now.return_value.strftime.return_value = "20240101_120000"

        # Remove the log file if it exists
        if os.name == "nt":  # Windows
            log_file = Path("C:/Windows/Temp/20240101_120000_py-libp2p.log")
        else:  # Unix-like
            log_file = Path("/tmp/20240101_120000_py-libp2p.log")
        log_file.unlink(missing_ok=True)

        setup_logging()

        # Wait for the listener to be ready
        _listener_ready.wait(timeout=1)

        logger = logging.getLogger("libp2p")
        logger.info("Test message")

        # Give the listener time to process the message
        await trio.sleep(0.1)

        # Stop the listener to ensure all messages are written
        if _current_listener is not None:
            _current_listener.stop()

        # Check the default log file
        if log_file.exists():  # Only check content if we have write permission
            content = log_file.read_text()
            assert "Test message" in content


def test_invalid_log_level(clean_env):
    """Test handling of invalid log level in LIBP2P_DEBUG."""
    os.environ["LIBP2P_DEBUG"] = "INVALID_LEVEL"
    setup_logging()
    logger = logging.getLogger("libp2p")

    # Should default to WARNING when invalid level is provided
    assert logger.level == logging.WARNING


def test_invalid_module_format(clean_env):
    """Test handling of invalid module format in LIBP2P_DEBUG."""
    os.environ["LIBP2P_DEBUG"] = "identity.identify:DEBUG,invalid_format"
    setup_logging()

    # The valid module should be configured
    identify_logger = logging.getLogger("libp2p.identity.identify")
    assert identify_logger.level == logging.DEBUG


def test_module_name_handling(clean_env):
    """Test various module name formats."""
    # Test multiple formats in one go
    os.environ["LIBP2P_DEBUG"] = (
        "identity.identify:DEBUG,"  # No libp2p prefix
        "libp2p.transport:INFO,"  # With libp2p prefix
        "pubsub/gossipsub:WARN"  # Using slash instead of dot
    )
    setup_logging()

    # Check each logger
    identify_logger = logging.getLogger("libp2p.identity.identify")
    assert identify_logger.level == logging.DEBUG

    transport_logger = logging.getLogger("libp2p.transport")
    assert transport_logger.level == logging.INFO

    gossipsub_logger = logging.getLogger("libp2p.pubsub.gossipsub")
    assert gossipsub_logger.level == logging.WARNING
