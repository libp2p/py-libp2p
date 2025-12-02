WebSocket Transport Examples
============================

This guide demonstrates how to use the WebSocket transport in py-libp2p, including WS (WebSocket) and WSS (WebSocket Secure) protocols, SOCKS proxy support, AutoTLS, and advanced configuration options.

Quick Start
-----------

Basic WebSocket transport setup:

.. code-block:: python

    from libp2p import new_host
    from libp2p.transport.websocket import WebsocketTransport, WebsocketConfig
    from libp2p.transport.upgrader import TransportUpgrader
    from multiaddr import Multiaddr

    # Create upgrader with security and muxer
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={...},
        muxer_transports_by_protocol={...}
    )

    # Create WebSocket transport
    config = WebsocketConfig()
    transport = WebsocketTransport(upgrader, config=config)

    # Create host with WebSocket transport
    host = new_host(
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")]
    )

WS vs WSS
---------

**WS (Insecure WebSocket):**

Use for development and testing. No TLS encryption:

.. code-block:: python

    ws_addr = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
    host = new_host(listen_addrs=[ws_addr])

**WSS (Secure WebSocket):**

Use for production. Requires TLS configuration:

.. code-block:: python

    import ssl

    # Create TLS context
    tls_context = ssl.create_default_context()
    tls_context.check_hostname = False
    tls_context.verify_mode = ssl.CERT_NONE  # For testing only

    # Configure transport with TLS
    config = WebsocketConfig(tls_server_config=tls_context)
    transport = WebsocketTransport(upgrader, config=config)

    wss_addr = Multiaddr("/ip4/127.0.0.1/tcp/8080/wss")
    host = new_host(listen_addrs=[wss_addr])

SOCKS Proxy Configuration
-------------------------

**Using Proxy Factory Function:**

.. code-block:: python

    from libp2p.transport.websocket import WithProxy

    # Configure with SOCKS5 proxy
    config = WithProxy(
        proxy_url="socks5://proxy.example.com:1080",
        auth=("username", "password")  # Optional
    )
    transport = WebsocketTransport(upgrader, config=config)

**Using Environment Variables:**

.. code-block:: python

    from libp2p.transport.websocket import WithProxyFromEnvironment

    # Reads HTTP_PROXY or HTTPS_PROXY environment variables
    config = WithProxyFromEnvironment()
    transport = WebsocketTransport(upgrader, config=config)

**Environment Variable Format:**

.. code-block:: bash

    export HTTP_PROXY=socks5://proxy.example.com:1080
    export HTTPS_PROXY=socks5://proxy.example.com:1080

AutoTLS Configuration
---------------------

AutoTLS automatically generates and manages TLS certificates for browser integration:

.. code-block:: python

    from libp2p.transport.websocket import WithAutoTLS, AutoTLSConfig

    autotls_config = AutoTLSConfig(
        enabled=True,
        default_domain="localhost",
        cert_validity_days=365
    )

    config = WithAutoTLS(autotls_config)
    transport = WebsocketTransport(upgrader, config=config)

**Browser Integration:**

AutoTLS is particularly useful for browser-based applications where you need trusted certificates for WebSocket connections.

Advanced TLS Configuration
---------------------------

For production deployments with custom certificates:

.. code-block:: python

    from libp2p.transport.websocket import WithAdvancedTLS
    from libp2p.transport.websocket.tls_config import (
        TLSConfig,
        CertificateValidationMode
    )

    tls_config = TLSConfig(
        cert_file="path/to/cert.pem",
        key_file="path/to/key.pem",
        ca_file="path/to/ca.pem",
        validation_mode=CertificateValidationMode.STRICT
    )

    config = WithAdvancedTLS(tls_config)
    transport = WebsocketTransport(upgrader, config=config)

Connection Management
---------------------

Configure connection limits and timeouts:

.. code-block:: python

    from libp2p.transport.websocket import (
        WithMaxConnections,
        WithHandshakeTimeout
    )

    config = WebsocketConfig(
        max_connections=1000,
        handshake_timeout=15.0,
        max_buffered_amount=4 * 1024 * 1024,  # 4MB
        max_message_size=32 * 1024 * 1024     # 32MB
    )

    transport = WebsocketTransport(upgrader, config=config)

**Monitoring Connection Statistics:**

.. code-block:: python

    # Get transport statistics
    stats = transport.get_stats()
    print(f"Total connections: {stats['total_connections']}")
    print(f"Current connections: {stats['current_connections']}")
    print(f"Failed connections: {stats['failed_connections']}")

    # Get connection details
    connections = await transport.get_connections()
    for conn_id, conn in connections.items():
        conn_stats = conn.get_stats()
        print(f"Connection {conn_id}: {conn_stats}")

Complete Example
----------------

A complete example demonstrating WebSocket transport with all features:

.. literalinclude:: ../examples/websocket/websocket_demo.py
    :language: python
    :linenos:

Multiaddr Formats
-----------------

WebSocket transport supports various multiaddr formats:

- **WS (Insecure):** ``/ip4/127.0.0.1/tcp/8080/ws``
- **WSS (Secure):** ``/ip4/127.0.0.1/tcp/8080/wss``
- **TLS/WS Format:** ``/ip4/127.0.0.1/tcp/8080/tls/ws``
- **IPv6:** ``/ip6/::1/tcp/8080/ws``
- **DNS:** ``/dns/example.com/tcp/443/wss``

Production Considerations
--------------------------

1. **Security:**
   - Always use WSS in production
   - Use proper CA-signed certificates
   - Enable certificate validation
   - AutoTLS is for development/testing only

2. **Performance:**
   - Configure appropriate connection limits
   - Set reasonable timeouts
   - Monitor connection statistics
   - Use connection pooling for high-traffic scenarios

3. **Error Handling:**
   - Handle ``OpenConnectionError`` for connection failures
   - Implement retry logic for transient failures
   - Monitor failed connection counts

4. **Proxy Configuration:**
   - Use environment variables for flexible deployment
   - Test proxy connectivity before production deployment
   - Monitor proxy connection statistics

See Also
--------

- :doc:`libp2p.transport.websocket` - Full API documentation
- :doc:`examples.echo` - Basic echo protocol example
- :doc:`examples.echo_quic` - QUIC transport example for comparison
