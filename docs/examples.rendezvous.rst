Rendezvous Protocol Demo
========================

This example demonstrates the **rendezvous protocol** for peer discovery in libp2p networks. The rendezvous protocol allows peers to register under namespaces and discover other peers within the same namespace, facilitating peer-to-peer communication without requiring direct connections.

Overview
--------

The rendezvous protocol consists of two main components:

1. **Rendezvous Server**: Acts as a registry where peers can register and discover each other
2. **Rendezvous Client**: Registers with the server and discovers other peers in the same namespace

Key Features
------------

- **Namespace-based Discovery**: Peers register under specific namespaces for organized discovery
- **Automatic Refresh**: Optional background refresh to maintain registrations and discovery cache
- **TTL Management**: Time-based expiration of registrations to prevent stale entries
- **Peer Advertisement**: Peers can advertise their presence and availability
- **Scalable Discovery**: Efficient peer discovery without flooding the network

Quick Start
-----------

1. **Install py-libp2p:**

.. code-block:: console

    $ python -m pip install libp2p

2. **Start a Rendezvous Server:**

.. code-block:: console

    $ python rendezvous.py --mode server
    2025-09-21 14:05:47,378 [INFO] [libp2p.discovery.rendezvous.service] Rendezvous service started
    2025-09-21 14:05:47,378 [INFO] [rendezvous_example] Rendezvous server started with peer ID: Qmey5ZN9WjvtjzYrDfv3NYUY61tusn1qyHAWpuT5vaWUUR
    2025-09-21 14:05:47,378 [INFO] [rendezvous_example] Listening on: /ip4/0.0.0.0/tcp/51302/p2p/Qmey5ZN9WjvtjzYrDfv3NYUY61tusn1qyHAWpuT5vaWUUR
    2025-09-21 14:05:47,378 [INFO] [rendezvous_example] To connect a client, use:
    2025-09-21 14:05:47,378 [INFO] [rendezvous_example]   python rendezvous.py --mode client --address /ip4/0.0.0.0/tcp/51302/p2p/Qmey5ZN9WjvtjzYrDfv3NYUY61tusn1qyHAWpuT5vaWUUR
    2025-09-21 14:05:47,378 [INFO] [rendezvous_example] Press Ctrl+C to stop...

3. **Connect Clients (in separate terminals):**

.. code-block:: console

    $ python rendezvous.py --mode client --address /ip4/0.0.0.0/tcp/51302/p2p/Qmey5ZN9WjvtjzYrDfv3NYUY61tusn1qyHAWpuT5vaWUUR
    2025-09-21 14:07:07,641 [INFO] [rendezvous_example] Connected to rendezvous server: Qmey5ZN9WjvtjzYrDfv3NYUY61tusn1qyHAWpuT5vaWUUR
    2025-09-21 14:07:07,641 [INFO] [rendezvous_example] Enable refresh: True
    2025-09-21 14:07:07,641 [INFO] [rendezvous_example] 🔄 Refresh mode enabled - discovery service running in background
    2025-09-21 14:07:07,642 [INFO] [rendezvous_example] Client started with peer ID: QmWyrP7nwTaDDaM4CayBybs6aATNM4CYmbmXDU6oPADN7Y
    2025-09-21 14:07:07,644 [INFO] [rendezvous_example] Registering in namespace 'rendezvous'...
    2025-09-21 14:07:07,645 [INFO] [rendezvous_example] ✓ Registered with TTL 7200s
    2025-09-21 14:07:08,652 [INFO] [rendezvous_example] Discovering peers in namespace 'rendezvous'...
    2025-09-21 14:07:08,653 [INFO] [rendezvous_example]   Found self: QmWyrP7nwTaDDaM4CayBybs6aATNM4CYmbmXDU6oPADN7Y
    2025-09-21 14:07:08,653 [INFO] [rendezvous_example] Total peers found: 1
    2025-09-21 14:07:08,653 [INFO] [rendezvous_example] No other peers found (only self)

Usage Examples
--------------

Basic Server
~~~~~~~~~~~~

Start a rendezvous server on a specific port:

.. code-block:: console

    $ python rendezvous.py --mode server --port 8080

Client with Custom Namespace
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Register and discover peers in a custom namespace:

.. code-block:: console

    $ python rendezvous.py --mode client --address <server_multiaddr> --namespace "my-app"

Client without Refresh
~~~~~~~~~~~~~~~~~~~~~~

Run a client without automatic refresh (single-shot mode):

.. code-block:: console

    $ python rendezvous.py --mode client --address <server_multiaddr> --refresh False

Verbose Logging
~~~~~~~~~~~~~~~

Enable debug logging for detailed information:

.. code-block:: console

    $ python rendezvous.py --mode server --verbose

Command Line Options
--------------------

.. code-block:: text

    usage: rendezvous.py [-h] [--mode {server,client}] [--address [ADDRESS]]
                         [-p PORT] [-n NAMESPACE] [-v] [-r]

    optional arguments:
      -h, --help            show this help message and exit
      --mode {server,client}
                            Run as server or client
      --address [ADDRESS]   Server multiaddr (required for client mode)
      -p PORT, --port PORT  Port for server to listen on (default: random)
      -n NAMESPACE, --namespace NAMESPACE
                            Namespace to register/discover in (default: rendezvous)
      -v, --verbose         Enable verbose logging
      -r, --refresh         Enable automatic refresh for registration and discovery cache

Protocol Flow
-------------

1. **Server Setup**: The rendezvous server starts and listens for incoming connections
2. **Client Connection**: Clients connect to the server using its multiaddr
3. **Registration**: Clients register themselves under a namespace with a TTL
4. **Discovery**: Clients query the server for other peers in the same namespace
5. **Refresh**: (Optional) Clients automatically refresh their registration before TTL expires
6. **Unregistration**: Clients cleanly unregister when shutting down

Key Components
--------------

RendezvousService
~~~~~~~~~~~~~~~~~

The server-side component that:

- Manages peer registrations by namespace
- Handles registration, unregistration, and discovery requests
- Automatically cleans up expired registrations
- Provides namespace statistics

RendezvousDiscovery
~~~~~~~~~~~~~~~~~~~

The client-side component that:

- Registers the local peer under namespaces
- Discovers other peers in namespaces
- Optionally runs background refresh tasks
- Manages registration TTL and cache refresh

Configuration
-------------

Default values can be customized:

.. code-block:: python

    from libp2p.discovery.rendezvous import config

    # Default namespace for registrations
    config.DEFAULT_NAMESPACE = "rendezvous"

    # Default TTL for registrations (2 hours)
    config.DEFAULT_TTL = 2 * 3600

    # Maximum number of registrations per namespace
    config.MAX_REGISTRATIONS = 1000

    # Maximum TTL allowed
    config.MAX_TTL = 24 * 3600  # 24 hours

Refresh Mode
------------

When refresh mode is enabled (default), the client:

- Automatically re-registers before the TTL expires (at 80% of TTL)
- Refreshes the discovery cache periodically
- Runs a background service using trio's structured concurrency
- Maintains long-term presence in the network

This is ideal for long-running applications that need continuous peer discovery.

Use Cases
---------

- **Distributed Applications**: Services that need to find each other dynamically
- **Gaming**: Players discovering game sessions or lobbies
- **Content Sharing**: Nodes advertising available content or services
- **Mesh Networks**: Peers discovering neighbors in decentralized networks
- **Service Discovery**: Microservices finding each other in P2P architectures

Error Handling
--------------

The implementation includes robust error handling:

- Connection failures to rendezvous servers
- Registration timeouts and failures
- Discovery query errors
- Background refresh task failures
- Network connectivity issues

Best Practices
--------------

1. **Use descriptive namespaces** to organize different types of peers
2. **Enable refresh mode** for long-running applications
3. **Set appropriate TTL values** based on your application's needs
4. **Handle connection failures** gracefully in production code
5. **Monitor namespace statistics** on the server for debugging
6. **Use verbose logging** during development and testing

Source Code
-----------

.. literalinclude:: ../examples/rendezvous/rendezvous.py
    :language: python
    :linenos:

API Reference
-------------

For detailed API documentation, see:

- :doc:`libp2p.discovery` - Discovery protocol interfaces
- :doc:`libp2p.discovery.rendezvous` - Rendezvous implementation details
