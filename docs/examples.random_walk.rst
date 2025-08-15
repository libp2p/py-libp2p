Random Walk Example
===================

This example demonstrates the Random Walk module's peer discovery capabilities using real libp2p hosts and Kademlia DHT.
It shows how the Random Walk module automatically discovers new peers and maintains routing table health.

The Random Walk implementation performs the following key operations:

* **Automatic Peer Discovery**: Generates random peer IDs and queries the DHT network to discover new peers
* **Routing Table Maintenance**: Periodically refreshes the routing table to maintain network connectivity
* **Connection Management**: Maintains optimal connections to healthy peers in the network
* **Real-time Statistics**: Displays routing table size, connected peers, and peerstore statistics

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ cd examples/random_walk
    $ python random_walk.py --mode server
    2025-08-12 19:51:25,424 - random-walk-example - INFO - === Random Walk Example for py-libp2p ===
    2025-08-12 19:51:25,424 - random-walk-example - INFO - Mode: server, Port: 0 Demo interval: 30s
    2025-08-12 19:51:25,426 - random-walk-example - INFO - Starting server node on port 45123
    2025-08-12 19:51:25,426 - random-walk-example - INFO - Node peer ID: 16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef
    2025-08-12 19:51:25,426 - random-walk-example - INFO - Node address: /ip4/0.0.0.0/tcp/45123/p2p/16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef
    2025-08-12 19:51:25,427 - random-walk-example - INFO - Initial routing table size: 0
    2025-08-12 19:51:25,427 - random-walk-example - INFO - DHT service started in SERVER mode
    2025-08-12 19:51:25,430 - libp2p.discovery.random_walk.rt_refresh_manager - INFO - RT Refresh Manager started
    2025-08-12 19:51:55,432 - random-walk-example - INFO - --- Iteration 1 ---
    2025-08-12 19:51:55,432 - random-walk-example - INFO - Routing table size: 15
    2025-08-12 19:51:55,432 - random-walk-example - INFO - Connected peers: 8
    2025-08-12 19:51:55,432 - random-walk-example - INFO - Peerstore size: 42

You can also run the example in client mode:

.. code-block:: console

    $ python random_walk.py --mode client
    2025-08-12 19:52:15,424 - random-walk-example - INFO - === Random Walk Example for py-libp2p ===
    2025-08-12 19:52:15,424 - random-walk-example - INFO - Mode: client, Port: 0 Demo interval: 30s
    2025-08-12 19:52:15,426 - random-walk-example - INFO - Starting client node on port 51234
    2025-08-12 19:52:15,426 - random-walk-example - INFO - Node peer ID: 16Uiu2HAmAbc123xyz...
    2025-08-12 19:52:15,427 - random-walk-example - INFO - DHT service started in CLIENT mode
    2025-08-12 19:52:45,432 - random-walk-example - INFO - --- Iteration 1 ---
    2025-08-12 19:52:45,432 - random-walk-example - INFO - Routing table size: 8
    2025-08-12 19:52:45,432 - random-walk-example - INFO - Connected peers: 5
    2025-08-12 19:52:45,432 - random-walk-example - INFO - Peerstore size: 25

Command Line Options
--------------------

The example supports several command-line options:

.. code-block:: console

    $ python random_walk.py --help
    usage: random_walk.py [-h] [--mode {server,client}] [--port PORT]
                         [--demo-interval DEMO_INTERVAL] [--verbose]

    Random Walk Example for py-libp2p Kademlia DHT

    optional arguments:
      -h, --help            show this help message and exit
      --mode {server,client}
                            Node mode: server (DHT server), or client (DHT client)
      --port PORT           Port to listen on (0 for random)
      --demo-interval DEMO_INTERVAL
                            Interval between random walk demonstrations in seconds
      --verbose             Enable verbose logging

Key Features Demonstrated
-------------------------

**Automatic Random Walk Discovery**
    The example shows how the Random Walk module automatically:

    * Generates random 256-bit peer IDs for discovery queries
    * Performs concurrent random walks to maximize peer discovery
    * Validates discovered peers and adds them to the routing table
    * Maintains routing table health through periodic refreshes

**Real-time Network Statistics**
    The example displays live statistics every 30 seconds (configurable):

    * **Routing Table Size**: Number of peers in the Kademlia routing table
    * **Connected Peers**: Number of actively connected peers
    * **Peerstore Size**: Total number of known peers with addresses

**Connection Management**
    The example includes sophisticated connection management:

    * Automatically maintains connections to healthy peers
    * Filters for compatible peers (TCP + IPv4 addresses)
    * Reconnects to maintain optimal network connectivity
    * Handles connection failures gracefully

**DHT Integration**
    Shows seamless integration between Random Walk and Kademlia DHT:

    * RT Refresh Manager coordinates with the DHT routing table
    * Peer discovery feeds directly into DHT operations
    * Both SERVER and CLIENT modes supported
    * Bootstrap connectivity to public IPFS nodes

Understanding the Output
------------------------

When you run the example, you'll see periodic statistics that show how the Random Walk module is working:

* **Initial Phase**: Routing table starts empty and quickly discovers peers
* **Growth Phase**: Routing table size increases as more peers are discovered
* **Maintenance Phase**: Routing table size stabilizes as the system maintains optimal peer connections

The Random Walk module runs automatically in the background, performing peer discovery queries every few minutes to ensure the routing table remains populated with fresh, reachable peers.

Configuration
-------------

The Random Walk module can be configured through the following parameters in ``libp2p.discovery.random_walk.config``:

* ``RANDOM_WALK_ENABLED``: Enable/disable automatic random walks (default: True)
* ``REFRESH_INTERVAL``: Time between automatic refreshes in seconds (default: 300)
* ``RANDOM_WALK_CONCURRENCY``: Number of concurrent random walks (default: 3)
* ``MIN_RT_REFRESH_THRESHOLD``: Minimum routing table size before triggering refresh (default: 4)

See Also
--------

* :doc:`examples.kademlia` - Kademlia DHT value storage and content routing
* :doc:`libp2p.discovery.random_walk` - Random Walk module API documentation
