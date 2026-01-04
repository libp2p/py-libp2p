"""
Test suite for logger name standardization.

This test suite verifies that all modules use `__name__` for logger names,
ensuring logger names match module paths and enabling proper LIBP2P_DEBUG control.
"""

import logging
import os

import pytest

from libp2p.utils.logging import (
    _current_handlers,
    _current_listener,
    setup_logging,
)


def _reset_logging():
    """Reset all logging state."""
    import time

    # Stop existing listener if any
    if _current_listener is not None:
        _current_listener.stop()

    # Close all file handlers
    for handler in _current_handlers:
        if isinstance(handler, logging.FileHandler):
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
    _current_handlers.clear()

    # Small delay for file handle release
    time.sleep(0.01)

    # Reset the root logger
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)

    # Clear all libp2p loggers
    for name in list(logging.Logger.manager.loggerDict.keys()):
        if name.startswith("libp2p"):
            del logging.Logger.manager.loggerDict[name]

    # Reset libp2p logger
    logger = logging.getLogger("libp2p")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.WARNING)


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


def test_logger_name_matches_module_path():
    """Test that logger names match their module paths using __name__."""
    # Import modules and check their logger names
    from libp2p.host import basic_host
    from libp2p.network import swarm
    from libp2p.pubsub import floodsub, gossipsub, pubsub, validators
    from libp2p.transport.tcp import tcp

    # Verify logger names match module paths
    assert swarm.logger.name == "libp2p.network.swarm"
    assert basic_host.logger.name == "libp2p.host.basic_host"
    assert tcp.logger.name == "libp2p.transport.tcp.tcp"
    assert pubsub.logger.name == "libp2p.pubsub.pubsub"
    assert floodsub.logger.name == "libp2p.pubsub.floodsub"
    assert gossipsub.logger.name == "libp2p.pubsub.gossipsub"
    assert validators.logger.name == "libp2p.pubsub.validators"


def test_logger_name_matches_module_path_relay():
    """Test relay circuit v2 modules use correct logger names."""
    from libp2p.relay.circuit_v2 import (
        discovery,
        nat,
        protocol,
        transport,
        utils,
    )

    assert transport.logger.name == "libp2p.relay.circuit_v2.transport"
    assert protocol.logger.name == "libp2p.relay.circuit_v2.protocol"
    assert discovery.logger.name == "libp2p.relay.circuit_v2.discovery"
    assert utils.logger.name == "libp2p.relay.circuit_v2.utils"
    assert nat.logger.name == "libp2p.relay.circuit_v2.nat"


def test_logger_name_matches_module_path_discovery():
    """Test discovery modules use correct logger names."""
    from libp2p.discovery.bootstrap import utils as bootstrap_utils
    import libp2p.discovery.bootstrap.bootstrap as bootstrap
    from libp2p.discovery.mdns import broadcaster, listener
    import libp2p.discovery.mdns.mdns as mdns
    from libp2p.discovery.random_walk import rt_refresh_manager
    import libp2p.discovery.random_walk.random_walk as random_walk
    import libp2p.discovery.upnp.upnp as upnp

    assert bootstrap.logger.name == "libp2p.discovery.bootstrap.bootstrap"
    assert bootstrap_utils.logger.name == "libp2p.discovery.bootstrap.utils"
    assert mdns.logger.name == "libp2p.discovery.mdns.mdns"
    assert listener.logger.name == "libp2p.discovery.mdns.listener"
    assert broadcaster.logger.name == "libp2p.discovery.mdns.broadcaster"
    assert random_walk.logger.name == "libp2p.discovery.random_walk.random_walk"
    assert (
        rt_refresh_manager.logger.name
        == "libp2p.discovery.random_walk.rt_refresh_manager"
    )
    assert upnp.logger.name == "libp2p.discovery.upnp.upnp"


def test_logger_name_matches_module_path_transport():
    """Test transport modules use correct logger names."""
    from libp2p.stream_muxer.mplex import mplex
    from libp2p.stream_muxer.yamux import yamux
    from libp2p.transport import transport_registry
    from libp2p.transport.websocket import autotls, listener

    assert listener.logger.name == "libp2p.transport.websocket.listener"
    assert autotls.logger.name == "libp2p.transport.websocket.autotls"
    assert transport_registry.logger.name == "libp2p.transport.transport_registry"
    assert yamux.logger.name == "libp2p.stream_muxer.yamux.yamux"
    assert mplex.logger.name == "libp2p.stream_muxer.mplex.mplex"


def test_logger_name_matches_module_path_host():
    """Test host modules use correct logger names."""
    from libp2p.host import ping
    import libp2p.host.autonat.autonat as autonat

    assert ping.logger.name == "libp2p.host.ping"
    assert autonat.logger.name == "libp2p.host.autonat.autonat"


def test_logger_name_matches_module_path_utils():
    """Test utils modules use correct logger names."""
    from libp2p.io import trio as io_trio
    from libp2p.protocol_muxer import multiselect_client
    from libp2p.utils import varint, version

    assert io_trio.logger.name == "libp2p.io.trio"
    assert version.logger.name == "libp2p.utils.version"
    assert varint.logger.name == "libp2p.utils.varint"
    assert multiselect_client.logger.name == "libp2p.protocol_muxer.multiselect_client"


def test_module_specific_logging_with_standardized_names(clean_env):
    """Test that module-specific logging works with standardized logger names."""
    os.environ["LIBP2P_DEBUG"] = (
        "network.swarm:DEBUG,"
        "pubsub:INFO,"
        "pubsub.gossipsub:WARNING,"
        "relay.circuit_v2.transport:DEBUG,"
        "discovery.bootstrap.bootstrap:INFO"
    )
    setup_logging()

    # Verify module-specific levels are set correctly
    swarm_logger = logging.getLogger("libp2p.network.swarm")
    assert swarm_logger.level == logging.DEBUG

    pubsub_logger = logging.getLogger("libp2p.pubsub")
    assert pubsub_logger.level == logging.INFO

    gossipsub_logger = logging.getLogger("libp2p.pubsub.gossipsub")
    assert gossipsub_logger.level == logging.WARNING

    relay_transport_logger = logging.getLogger("libp2p.relay.circuit_v2.transport")
    assert relay_transport_logger.level == logging.DEBUG

    bootstrap_logger = logging.getLogger("libp2p.discovery.bootstrap.bootstrap")
    assert bootstrap_logger.level == logging.INFO


def test_logger_inheritance_with_standardized_names(clean_env):
    """Test that child loggers inherit from parent loggers correctly."""
    os.environ["LIBP2P_DEBUG"] = "pubsub:DEBUG"
    setup_logging()

    # Parent logger should be at DEBUG
    pubsub_logger = logging.getLogger("libp2p.pubsub")
    assert pubsub_logger.level == logging.DEBUG

    # Child loggers should inherit DEBUG level
    gossipsub_logger = logging.getLogger("libp2p.pubsub.gossipsub")
    assert gossipsub_logger.getEffectiveLevel() == logging.DEBUG

    floodsub_logger = logging.getLogger("libp2p.pubsub.floodsub")
    assert floodsub_logger.getEffectiveLevel() == logging.DEBUG


def test_logger_effective_level_with_module_specific_config(clean_env):
    """Test effective log levels with module-specific configuration."""
    os.environ["LIBP2P_DEBUG"] = "INFO,network.swarm:DEBUG,host.ping:WARNING"
    setup_logging()

    # Root should be at INFO
    root_logger = logging.getLogger("libp2p")
    assert root_logger.level == logging.INFO

    # Swarm should be at DEBUG (overrides root)
    swarm_logger = logging.getLogger("libp2p.network.swarm")
    assert swarm_logger.level == logging.DEBUG

    # Ping should be at WARNING (overrides root)
    ping_logger = logging.getLogger("libp2p.host.ping")
    assert ping_logger.level == logging.WARNING

    # Unspecified module should inherit INFO from root
    transport_logger = logging.getLogger("libp2p.transport.tcp.tcp")
    assert transport_logger.getEffectiveLevel() == logging.INFO


def test_logger_names_are_consistent_across_imports():
    """Test that logger names remain consistent across multiple imports."""
    # Import modules multiple times
    # Re-import (should get same module)
    import importlib

    from libp2p.network import swarm as swarm1
    from libp2p.pubsub import pubsub as pubsub1

    swarm2 = importlib.reload(swarm1)
    pubsub2 = importlib.reload(pubsub1)

    # Logger names should be consistent
    assert swarm1.logger.name == swarm2.logger.name
    assert pubsub1.logger.name == pubsub2.logger.name
    assert swarm1.logger.name == "libp2p.network.swarm"
    assert pubsub1.logger.name == "libp2p.pubsub.pubsub"


def test_logger_uses_name_attribute():
    """Test that loggers are created using __name__ pattern."""
    # Import a module and verify the logger was created with __name__
    from libp2p.network import swarm

    # The logger name should match the module's __name__
    assert swarm.logger.name == swarm.__name__  # type: ignore[attr-defined]

    # Verify for multiple modules
    from libp2p.pubsub import gossipsub

    assert gossipsub.logger.name == gossipsub.__name__  # type: ignore[attr-defined]

    from libp2p.relay.circuit_v2 import transport

    assert transport.logger.name == transport.__name__  # type: ignore[attr-defined]


def test_all_updated_modules_have_correct_logger_names():
    """Comprehensive test to verify all updated modules have correct logger names."""
    # Import all updated modules and verify their logger names
    from libp2p.discovery.bootstrap import utils as bootstrap_utils_module
    import libp2p.discovery.bootstrap.bootstrap as bootstrap_module
    from libp2p.discovery.mdns import broadcaster, listener
    import libp2p.discovery.mdns.mdns as mdns
    from libp2p.discovery.random_walk import rt_refresh_manager
    import libp2p.discovery.random_walk.random_walk as random_walk
    import libp2p.discovery.upnp.upnp as upnp
    from libp2p.host import basic_host, ping
    import libp2p.host.autonat.autonat as autonat
    from libp2p.io import trio as io_trio
    from libp2p.network import swarm
    from libp2p.protocol_muxer import multiselect_client
    from libp2p.pubsub import floodsub, gossipsub, pubsub, validators
    from libp2p.relay.circuit_v2 import discovery, nat, protocol, transport, utils
    from libp2p.stream_muxer.mplex import mplex
    from libp2p.stream_muxer.yamux import yamux
    from libp2p.transport import transport_registry
    from libp2p.transport.tcp import tcp
    from libp2p.transport.websocket import (
        autotls,
        listener as ws_listener,
    )
    from libp2p.utils import varint, version

    # Verify all logger names match their module paths
    test_cases = [
        (swarm, "libp2p.network.swarm"),
        (basic_host, "libp2p.host.basic_host"),
        (tcp, "libp2p.transport.tcp.tcp"),
        (pubsub, "libp2p.pubsub.pubsub"),
        (floodsub, "libp2p.pubsub.floodsub"),
        (gossipsub, "libp2p.pubsub.gossipsub"),
        (validators, "libp2p.pubsub.validators"),
        (transport, "libp2p.relay.circuit_v2.transport"),
        (protocol, "libp2p.relay.circuit_v2.protocol"),
        (discovery, "libp2p.relay.circuit_v2.discovery"),
        (utils, "libp2p.relay.circuit_v2.utils"),
        (nat, "libp2p.relay.circuit_v2.nat"),
        (bootstrap_module, "libp2p.discovery.bootstrap.bootstrap"),
        (bootstrap_utils_module, "libp2p.discovery.bootstrap.utils"),
        (mdns, "libp2p.discovery.mdns.mdns"),
        (listener, "libp2p.discovery.mdns.listener"),
        (broadcaster, "libp2p.discovery.mdns.broadcaster"),
        (random_walk, "libp2p.discovery.random_walk.random_walk"),
        (rt_refresh_manager, "libp2p.discovery.random_walk.rt_refresh_manager"),
        (upnp, "libp2p.discovery.upnp.upnp"),
        (ping, "libp2p.host.ping"),
        (autonat, "libp2p.host.autonat.autonat"),
        (multiselect_client, "libp2p.protocol_muxer.multiselect_client"),
        (io_trio, "libp2p.io.trio"),
        (version, "libp2p.utils.version"),
        (varint, "libp2p.utils.varint"),
        (ws_listener, "libp2p.transport.websocket.listener"),
        (autotls, "libp2p.transport.websocket.autotls"),
        (transport_registry, "libp2p.transport.transport_registry"),
        (yamux, "libp2p.stream_muxer.yamux.yamux"),
        (mplex, "libp2p.stream_muxer.mplex.mplex"),
    ]

    for module, expected_name in test_cases:
        logger = getattr(module, "logger", None)
        assert logger is not None, f"Module {expected_name} should have a logger"
        assert logger.name == expected_name, (
            f"Logger name mismatch for {expected_name}: "
            f"expected {expected_name}, got {logger.name}"
        )
