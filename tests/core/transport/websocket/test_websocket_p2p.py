"""
WebSocket Peer-to-Peer Configuration and Proxy Tests.

This module tests WebSocket transport configuration including:
- AutoTLS configuration integration
- Proxy support (SOCKS4/SOCKS5) configuration
- Environment variable proxy detection
- Transport configuration options

Note: Full P2P connection tests are skipped due to a known issue with
security handshake failures in the InsecureTransport implementation.
See: https://github.com/libp2p/py-libp2p/issues/938

For working P2P examples, see: examples/autotls_browser/main.py
"""

from pathlib import Path
import tempfile

import pytest

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.autotls import AutoTLSConfig
from libp2p.transport.websocket.transport import (
    WebsocketConfig,
    WebsocketTransport,
)

PLAINTEXT_PROTOCOL_ID = "/plaintext/1.0.0"


class TestWebSocketProxySupport:
    """Test WebSocket proxy configuration."""

    @pytest.mark.trio
    async def test_proxy_config_creation(self) -> None:
        """Test creating WebSocket config with proxy settings."""
        # Test proxy configuration
        ws_config = WebsocketConfig()
        ws_config.proxy_url = "socks5://localhost:1080"

        assert ws_config.proxy_url == "socks5://localhost:1080"

    @pytest.mark.trio
    async def test_proxy_with_auth(self) -> None:
        """Test proxy configuration with authentication."""
        ws_config = WebsocketConfig()
        ws_config.proxy_url = "socks5://user:pass@localhost:1080"

        assert ws_config.proxy_url == "socks5://user:pass@localhost:1080"

    @pytest.mark.trio
    async def test_environment_proxy_detection(self) -> None:
        """Test environment variable proxy detection."""
        import os

        from libp2p.transport.websocket.proxy_env import (
            get_proxy_from_environment,
        )

        # Test HTTP_PROXY for ws://
        os.environ["HTTP_PROXY"] = "socks5://proxy.test:1080"
        try:
            proxy = get_proxy_from_environment("ws://example.com")
            assert proxy == "socks5://proxy.test:1080"
        finally:
            del os.environ["HTTP_PROXY"]

        # Test HTTPS_PROXY for wss://
        os.environ["HTTPS_PROXY"] = "socks5://secure-proxy.test:1080"
        try:
            proxy = get_proxy_from_environment("wss://secure.example.com")
            assert proxy == "socks5://secure-proxy.test:1080"
        finally:
            del os.environ["HTTPS_PROXY"]

    @pytest.mark.trio
    async def test_no_proxy_bypass(self) -> None:
        """Test NO_PROXY bypass functionality."""
        import os

        from libp2p.transport.websocket.proxy_env import (
            get_proxy_from_environment,
        )

        os.environ["HTTP_PROXY"] = "socks5://proxy.test:1080"
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"

        try:
            # Should bypass proxy for localhost
            proxy = get_proxy_from_environment("ws://localhost:8080")
            assert proxy is None

            # Should bypass proxy for 127.0.0.1
            proxy = get_proxy_from_environment("ws://127.0.0.1:8080")
            assert proxy is None

            # Should use proxy for other hosts
            proxy = get_proxy_from_environment("ws://example.com:8080")
            assert proxy == "socks5://proxy.test:1080"
        finally:
            del os.environ["HTTP_PROXY"]
            del os.environ["NO_PROXY"]

    @pytest.mark.trio
    async def test_proxy_url_parsing(self) -> None:
        """Test proxy URL parsing for different schemes."""
        import os

        from libp2p.transport.websocket.proxy_env import (
            get_proxy_from_environment,
        )

        # Test SOCKS5
        os.environ["HTTP_PROXY"] = "socks5://proxy:1080"
        try:
            proxy = get_proxy_from_environment("ws://test.com")
            assert proxy == "socks5://proxy:1080"
        finally:
            del os.environ["HTTP_PROXY"]

        # Test SOCKS4
        os.environ["HTTP_PROXY"] = "socks4://proxy:1080"
        try:
            proxy = get_proxy_from_environment("ws://test.com")
            assert proxy == "socks4://proxy:1080"
        finally:
            del os.environ["HTTP_PROXY"]


class TestWebSocketConfigOptions:
    """Test WebSocket transport configuration options."""

    @pytest.mark.trio
    async def test_config_with_custom_settings(self) -> None:
        """Test WebSocket config with custom settings."""
        ws_config = WebsocketConfig()
        ws_config.max_connections = 100
        ws_config.handshake_timeout = 30.0
        ws_config.close_timeout = 10.0

        # Create transport with custom config
        key_pair = create_new_key_pair()
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )

        transport = WebsocketTransport(upgrader, config=ws_config)

        # Verify config is applied
        assert transport._config.max_connections == 100
        assert transport._config.handshake_timeout == 30.0
        assert transport._config.close_timeout == 10.0

    @pytest.mark.trio
    async def test_autotls_config_integration(self) -> None:
        """Test AutoTLS config integration with WebSocket transport."""
        with tempfile.TemporaryDirectory() as temp_dir:
            autotls_config = AutoTLSConfig(
                enabled=True,
                storage_path=Path(temp_dir),
                default_domain="test.local",
                cert_validity_days=30,
            )

            ws_config = WebsocketConfig()
            ws_config.autotls_config = autotls_config

            # Create transport
            key_pair = create_new_key_pair()
            upgrader = TransportUpgrader(
                secure_transports_by_protocol={
                    TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
                },
                muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
            )

            transport = WebsocketTransport(upgrader, config=ws_config)

            # Verify AutoTLS is configured
            assert transport._config.autotls_config is not None
            assert transport._config.autotls_config.enabled is True
            assert transport._config.autotls_config.default_domain == "test.local"

    @pytest.mark.trio
    async def test_websocket_config_defaults(self) -> None:
        """Test WebSocket config default values."""
        ws_config = WebsocketConfig()

        # Verify default values
        assert ws_config.max_connections == 1000
        assert ws_config.handshake_timeout == 15.0
        assert ws_config.proxy_url is None
        assert ws_config.autotls_config is None

    @pytest.mark.trio
    async def test_websocket_config_with_all_options(self) -> None:
        """Test WebSocket config with all options configured."""
        with tempfile.TemporaryDirectory() as temp_dir:
            autotls_config = AutoTLSConfig(
                enabled=True,
                storage_path=Path(temp_dir),
                default_domain="test.local",
            )

            ws_config = WebsocketConfig()
            ws_config.max_connections = 500
            ws_config.handshake_timeout = 45.0
            ws_config.proxy_url = "socks5://proxy.local:1080"
            ws_config.autotls_config = autotls_config

            # Verify all settings
            assert ws_config.max_connections == 500
            assert ws_config.handshake_timeout == 45.0
            assert ws_config.proxy_url == "socks5://proxy.local:1080"
            assert ws_config.autotls_config is not None
            assert ws_config.autotls_config.enabled is True


class TestWebSocketTransportCreation:
    """Test WebSocket transport creation with various configurations."""

    @pytest.mark.trio
    async def test_transport_basic_creation(self) -> None:
        """Test creating basic WebSocket transport."""
        key_pair = create_new_key_pair()
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )

        transport = WebsocketTransport(upgrader)

        # Verify transport was created
        assert transport is not None
        assert hasattr(transport, "dial")
        assert hasattr(transport, "create_listener")

    @pytest.mark.trio
    async def test_transport_with_proxy_config(self) -> None:
        """Test creating WebSocket transport with proxy configuration."""
        key_pair = create_new_key_pair()
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )

        ws_config = WebsocketConfig()
        ws_config.proxy_url = "socks5://proxy.local:1080"

        transport = WebsocketTransport(upgrader, config=ws_config)

        # Verify config is set
        assert transport._config.proxy_url == "socks5://proxy.local:1080"

    @pytest.mark.trio
    async def test_transport_with_autotls(self) -> None:
        """Test creating WebSocket transport with AutoTLS."""
        with tempfile.TemporaryDirectory() as temp_dir:
            autotls_config = AutoTLSConfig(
                enabled=True,
                storage_path=Path(temp_dir),
                default_domain="localhost",
                cert_validity_days=7,
            )

            key_pair = create_new_key_pair()
            upgrader = TransportUpgrader(
                secure_transports_by_protocol={
                    TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
                },
                muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
            )

            ws_config = WebsocketConfig()
            ws_config.autotls_config = autotls_config

            transport = WebsocketTransport(upgrader, config=ws_config)

            # Verify AutoTLS is configured
            assert transport._config.autotls_config is not None
            assert transport._config.autotls_config.enabled is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
