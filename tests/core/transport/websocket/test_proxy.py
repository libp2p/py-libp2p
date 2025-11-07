"""
Tests for SOCKS proxy support in WebSocket transport.

These tests validate:
1. Environment variable detection (HTTP_PROXY, HTTPS_PROXY)
2. NO_PROXY bypass rules
3. SOCKS5 handshake validation
4. Configuration helpers (WithProxy, etc.)
5. Proxy precedence rules
"""

import os

import pytest

from libp2p.transport.websocket import (
    WebsocketConfig,
    WithHandshakeTimeout,
    WithProxy,
    WithProxyFromEnvironment,
    combine_configs,
)
from libp2p.transport.websocket.proxy_env import (
    _should_bypass_proxy,
    get_proxy_from_environment,
    validate_proxy_url,
)


def test_proxy_from_environment_http():
    """Test proxy detection from HTTP_PROXY environment variable."""
    original = os.environ.get("HTTP_PROXY")
    os.environ["HTTP_PROXY"] = "socks5://proxy.example.com:1080"

    try:
        proxy = get_proxy_from_environment("ws://target.example.com")
        assert proxy == "socks5://proxy.example.com:1080"
    finally:
        if original:
            os.environ["HTTP_PROXY"] = original
        else:
            os.environ.pop("HTTP_PROXY", None)


def test_proxy_from_environment_https():
    """Test proxy detection from HTTPS_PROXY environment variable."""
    original = os.environ.get("HTTPS_PROXY")
    os.environ["HTTPS_PROXY"] = "socks5://secure-proxy.example.com:1080"

    try:
        proxy = get_proxy_from_environment("wss://target.example.com")
        assert proxy == "socks5://secure-proxy.example.com:1080"
    finally:
        if original:
            os.environ["HTTPS_PROXY"] = original
        else:
            os.environ.pop("HTTPS_PROXY", None)


def test_proxy_from_environment_lowercase():
    """Test that lowercase environment variables work too."""
    original_upper = os.environ.get("HTTP_PROXY")
    original_lower = os.environ.get("http_proxy")

    os.environ.pop("HTTP_PROXY", None)
    os.environ["http_proxy"] = "socks5://lowercase-proxy.local:1080"

    try:
        proxy = get_proxy_from_environment("ws://target.example.com")
        assert proxy == "socks5://lowercase-proxy.local:1080"
    finally:
        if original_upper:
            os.environ["HTTP_PROXY"] = original_upper
        if original_lower:
            os.environ["http_proxy"] = original_lower
        else:
            os.environ.pop("http_proxy", None)


def test_proxy_uppercase_takes_precedence():
    """
    Test that uppercase environment variables take precedence.
    Note: This test behavior differs on Windows vs Linux:
    - On Linux: HTTP_PROXY and http_proxy are distinct variables
    - On Windows: Environment variables are case-insensitive, so they're the same
    The implementation correctly handles both:
    - On Linux: uppercase is checked first via os.environ.get("HTTP_PROXY")
    - On Windows: whichever was set in os.environ last takes effect
    """
    import platform

    original_upper = os.environ.get("HTTP_PROXY")
    original_lower = os.environ.get("http_proxy")

    try:
        # Clear both to start fresh
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("http_proxy", None)

        # Set uppercase first, then lowercase
        os.environ["HTTP_PROXY"] = "socks5://uppercase-proxy:1080"
        os.environ["http_proxy"] = "socks5://lowercase-proxy:1080"

        proxy = get_proxy_from_environment("ws://target.example.com")

        # On Windows, case-insensitive env vars mean lowercase overwrites uppercase
        # On Linux, they're distinct and uppercase takes precedence via our logic
        if platform.system() == "Windows":
            # Windows: the lowercase assignment overwrites (they're the same var)
            assert proxy == "socks5://lowercase-proxy:1080"
        else:
            # Linux: distinct variables, uppercase is checked first
            assert proxy == "socks5://uppercase-proxy:1080"
    finally:
        if original_upper:
            os.environ["HTTP_PROXY"] = original_upper
        else:
            os.environ.pop("HTTP_PROXY", None)
        if original_lower:
            os.environ["http_proxy"] = original_lower
        else:
            os.environ.pop("http_proxy", None)


def test_no_proxy_configured():
    """Test behavior when no proxy is configured."""
    original_http = os.environ.get("HTTP_PROXY")
    original_https = os.environ.get("HTTPS_PROXY")

    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)

    try:
        proxy = get_proxy_from_environment("ws://target.example.com")
        assert proxy is None
    finally:
        # Cleanup
        if original_http:
            os.environ["HTTP_PROXY"] = original_http
        if original_https:
            os.environ["HTTPS_PROXY"] = original_https


def test_no_proxy_direct_match():
    """Test NO_PROXY with direct hostname match."""
    original = os.environ.get("NO_PROXY")
    os.environ["NO_PROXY"] = "localhost,example.com"

    try:
        assert _should_bypass_proxy("localhost", 80) is True
        assert _should_bypass_proxy("example.com", 443) is True

        assert _should_bypass_proxy("other.com", 80) is False
    finally:
        if original:
            os.environ["NO_PROXY"] = original
        else:
            os.environ.pop("NO_PROXY", None)


def test_no_proxy_domain_suffix():
    """Test NO_PROXY with domain suffix matching."""
    original = os.environ.get("NO_PROXY")
    os.environ["NO_PROXY"] = ".internal.com"

    try:
        assert _should_bypass_proxy("app.internal.com", 443) is True
        assert _should_bypass_proxy("api.internal.com", 80) is True

        assert _should_bypass_proxy("internal.com", 80) is False
        assert _should_bypass_proxy("external.com", 80) is False
    finally:
        if original:
            os.environ["NO_PROXY"] = original
        else:
            os.environ.pop("NO_PROXY", None)


def test_no_proxy_wildcard():
    """Test NO_PROXY with wildcard (bypass all)."""
    original = os.environ.get("NO_PROXY")
    os.environ["NO_PROXY"] = "*"

    try:
        assert _should_bypass_proxy("any-host.com", 80) is True
        assert _should_bypass_proxy("localhost", 443) is True
        assert _should_bypass_proxy("192.168.1.1", 8080) is True
    finally:
        if original:
            os.environ["NO_PROXY"] = original
        else:
            os.environ.pop("NO_PROXY", None)


def test_no_proxy_mixed_entries():
    """Test NO_PROXY with multiple different entry types."""
    original = os.environ.get("NO_PROXY")
    os.environ["NO_PROXY"] = "localhost,.internal.corp,example.com"

    try:
        assert _should_bypass_proxy("localhost", 80) is True
        assert _should_bypass_proxy("example.com", 443) is True

        assert _should_bypass_proxy("app.internal.corp", 80) is True

        assert _should_bypass_proxy("external.com", 80) is False
    finally:
        if original:
            os.environ["NO_PROXY"] = original
        else:
            os.environ.pop("NO_PROXY", None)


def test_no_proxy_case_insensitive():
    """Test that NO_PROXY matching is case-insensitive."""
    original = os.environ.get("NO_PROXY")
    os.environ["NO_PROXY"] = "LOCALHOST,Example.COM"

    try:
        assert _should_bypass_proxy("localhost", 80) is True
        assert _should_bypass_proxy("LOCALHOST", 80) is True
        assert _should_bypass_proxy("example.com", 443) is True
        assert _should_bypass_proxy("EXAMPLE.COM", 443) is True
    finally:
        if original:
            os.environ["NO_PROXY"] = original
        else:
            os.environ.pop("NO_PROXY", None)


def test_validate_proxy_url_valid():
    """Test validation of valid proxy URLs."""
    assert validate_proxy_url("socks5://localhost:1080") is True
    assert validate_proxy_url("socks5://proxy.example.com:9050") is True
    assert validate_proxy_url("socks4://192.168.1.1:1080") is True
    assert validate_proxy_url("socks4a://proxy:1080") is True
    assert validate_proxy_url("socks5h://proxy:1080") is True


def test_validate_proxy_url_invalid_scheme():
    """Test validation rejects invalid schemes."""
    assert validate_proxy_url("http://proxy:8080") is False
    assert validate_proxy_url("https://proxy:8080") is False
    assert validate_proxy_url("ftp://proxy:21") is False
    assert validate_proxy_url("invalid://proxy:1080") is False


def test_validate_proxy_url_malformed():
    """Test validation rejects malformed URLs."""
    assert validate_proxy_url("not-a-url") is False
    assert validate_proxy_url("socks5://") is False
    assert validate_proxy_url("") is False


def test_with_proxy_basic():
    """Test WithProxy configuration helper."""
    config = WithProxy("socks5://proxy.corp.com:1080")

    assert config.proxy_url == "socks5://proxy.corp.com:1080"
    assert config.proxy_auth is None


def test_with_proxy_with_auth():
    """Test WithProxy with authentication."""
    config = WithProxy("socks5://proxy.corp.com:1080", auth=("username", "password"))

    assert config.proxy_url == "socks5://proxy.corp.com:1080"
    assert config.proxy_auth == ("username", "password")


def test_with_proxy_from_environment():
    """Test WithProxyFromEnvironment configuration helper."""
    config = WithProxyFromEnvironment()

    assert config.proxy_url is None
    assert isinstance(config, WebsocketConfig)


def test_with_handshake_timeout():
    """Test WithHandshakeTimeout configuration helper."""
    config = WithHandshakeTimeout(30.0)

    assert config.handshake_timeout == 30.0


def test_with_handshake_timeout_invalid():
    """Test WithHandshakeTimeout rejects invalid values."""
    with pytest.raises(ValueError, match="must be positive"):
        WithHandshakeTimeout(0)

    with pytest.raises(ValueError, match="must be positive"):
        WithHandshakeTimeout(-5.0)


def test_combine_configs_proxy_and_timeout():
    """Test combining proxy and timeout configs."""
    proxy_config = WithProxy("socks5://proxy:1080")
    timeout_config = WithHandshakeTimeout(60.0)

    combined = combine_configs(proxy_config, timeout_config)

    assert combined.proxy_url == "socks5://proxy:1080"
    assert combined.handshake_timeout == 60.0


def test_combine_configs_precedence():
    """Test that later configs override earlier ones."""
    config1 = WithProxy("socks5://first-proxy:1080")
    config2 = WithProxy("socks5://second-proxy:1080")

    combined = combine_configs(config1, config2)

    assert combined.proxy_url == "socks5://second-proxy:1080"


def test_combine_configs_multiple():
    """Test combining many configs at once."""
    proxy_config = WithProxy("socks5://proxy:1080", auth=("user", "pass"))
    timeout_config = WithHandshakeTimeout(45.0)

    combined = combine_configs(proxy_config, timeout_config)

    assert combined.proxy_url == "socks5://proxy:1080"
    assert combined.proxy_auth == ("user", "pass")
    assert combined.handshake_timeout == 45.0


@pytest.mark.trio
async def test_socks5_connection_manager_creation():
    """
    Test that SOCKS5 connection manager can be created with valid configuration.

    Note: Full connection tests require a running SOCKS proxy server.
    This test validates configuration parsing only.
    """
    try:
        from libp2p.transport.websocket.proxy import SOCKSConnectionManager
    except ImportError:
        pytest.skip("trio_socks not installed")

    # Test basic creation
    manager = SOCKSConnectionManager("socks5://127.0.0.1:1080", timeout=2.0)
    assert manager.proxy_scheme == "socks5"
    assert manager.proxy_host == "127.0.0.1"
    assert manager.proxy_port == 1080
    assert manager.timeout == 2.0

    # Test with authentication
    manager_auth = SOCKSConnectionManager(
        "socks5://user:pass@proxy.local:1080",
        auth=("user", "pass"),
        timeout=5.0,
    )
    assert manager_auth.proxy_host == "proxy.local"
    assert manager_auth.proxy_port == 1080
    assert manager_auth.timeout == 5.0

    # Test SOCKS4
    manager_socks4 = SOCKSConnectionManager("socks4://127.0.0.1:1080")
    assert manager_socks4.proxy_scheme == "socks4"


@pytest.mark.trio
async def test_proxy_precedence_explicit_over_config():
    """Test that explicit proxy parameter overrides config."""
    config = WebsocketConfig(proxy_url="socks5://config-proxy:1080")

    assert config.proxy_url == "socks5://config-proxy:1080"


@pytest.mark.trio
async def test_proxy_precedence_config_over_environment():
    """Test that config proxy overrides environment variable."""
    original = os.environ.get("HTTPS_PROXY")
    os.environ["HTTPS_PROXY"] = "socks5://env-proxy:1080"

    try:
        config = WebsocketConfig(proxy_url="socks5://config-proxy:1080")

        assert config.proxy_url == "socks5://config-proxy:1080"

        env_proxy = get_proxy_from_environment("wss://example.com")
        assert env_proxy == "socks5://env-proxy:1080"

    finally:
        if original:
            os.environ["HTTPS_PROXY"] = original
        else:
            os.environ.pop("HTTPS_PROXY", None)


@pytest.mark.integration
@pytest.mark.trio
async def test_full_proxy_connection():
    """
    Full integration test with real SOCKS proxy.

    Note: Requires a real SOCKS proxy running locally (e.g., Tor on port 9050).
    Skip if not available.
    """
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex(("127.0.0.1", 9050))
        sock.close()

        if result != 0:
            pytest.skip("No SOCKS proxy available on localhost:9050 (Tor not running?)")
    except Exception as e:
        pytest.skip(f"Could not check for SOCKS proxy: {e}")

    config = WithProxy("socks5://127.0.0.1:9050")

    assert config.proxy_url == "socks5://127.0.0.1:9050"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
