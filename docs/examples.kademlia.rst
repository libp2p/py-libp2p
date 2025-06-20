Kademlia DHT Demo
=================

This example demonstrates a Kademlia Distributed Hash Table (DHT) implementation with both value storage/retrieval and content provider advertisement/discovery functionality.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ cd examples/kademlia
    $ python kademlia.py --mode server
    2025-06-13 19:51:25,424 - kademlia-example - INFO - Running in server mode on port 0
    2025-06-13 19:51:25,426 - kademlia-example - INFO - Connected to bootstrap nodes: []
    2025-06-13 19:51:25,426 - kademlia-example - INFO - To connect to this node, use: --bootstrap /ip4/127.0.0.1/tcp/28910/p2p/16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef
    2025-06-13 19:51:25,426 - kademlia-example - INFO - Saved server address to log: /ip4/127.0.0.1/tcp/28910/p2p/16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef
    2025-06-13 19:51:25,427 - kademlia-example - INFO - DHT service started in SERVER mode
    2025-06-13 19:51:25,427 - kademlia-example - INFO - Stored value 'Hello message from Sumanjeet' with key: FVDjasarSFDoLPMdgnp1dHSbW2ZAfN8NU2zNbCQeczgP
    2025-06-13 19:51:25,427 - kademlia-example - INFO - Successfully advertised as server for content: 361f2ed1183bca491b8aec11f0b9e5c06724759b0f7480ae7fb4894901993bc8


Copy the line that starts with ``--bootstrap``, open a new terminal in the same folder and run the client:

.. code-block:: console

    $ python kademlia.py --mode client --bootstrap /ip4/127.0.0.1/tcp/28910/p2p/16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef
    2025-06-13 19:51:37,022 - kademlia-example - INFO - Running in client mode on port 0
    2025-06-13 19:51:37,026 - kademlia-example - INFO - Connected to bootstrap nodes: [<libp2p.peer.id.ID (16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef)>]
    2025-06-13 19:51:37,027 - kademlia-example - INFO - DHT service started in CLIENT mode
    2025-06-13 19:51:37,027 - kademlia-example - INFO - Looking up key: FVDjasarSFDoLPMdgnp1dHSbW2ZAfN8NU2zNbCQeczgP
    2025-06-13 19:51:37,031 - kademlia-example - INFO - Retrieved value: Hello message from Sumanjeet
    2025-06-13 19:51:37,031 - kademlia-example - INFO - Looking for servers of content: 361f2ed1183bca491b8aec11f0b9e5c06724759b0f7480ae7fb4894901993bc8
    2025-06-13 19:51:37,035 - kademlia-example - INFO - Found 1 servers for content: ['16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef']

Alternatively, if you run the server first, the client can automatically extract the bootstrap address from the server log file:

.. code-block:: console

    $ python kademlia.py --mode client
    2025-06-13 19:51:37,022 - kademlia-example - INFO - Running in client mode on port 0
    2025-06-13 19:51:37,026 - kademlia-example - INFO - Connected to bootstrap nodes: [<libp2p.peer.id.ID (16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef)>]
    2025-06-13 19:51:37,027 - kademlia-example - INFO - DHT service started in CLIENT mode
    2025-06-13 19:51:37,027 - kademlia-example - INFO - Looking up key: FVDjasarSFDoLPMdgnp1dHSbW2ZAfN8NU2zNbCQeczgP
    2025-06-13 19:51:37,031 - kademlia-example - INFO - Retrieved value: Hello message from Sumanjeet
    2025-06-13 19:51:37,031 - kademlia-example - INFO - Looking for servers of content: 361f2ed1183bca491b8aec11f0b9e5c06724759b0f7480ae7fb4894901993bc8
    2025-06-13 19:51:37,035 - kademlia-example - INFO - Found 1 servers for content: ['16Uiu2HAm7EsNv5vvjPAehGAVfChjYjD63ZHyWogQRdzntSbAg9ef']

The demo showcases key DHT operations:

- **Value Storage & Retrieval**: The server stores a value, and the client retrieves it
- **Content Provider Discovery**: The server advertises content, and the client finds providers
- **Peer Discovery**: Automatic bootstrap and peer routing using the Kademlia algorithm
- **Network Resilience**: Distributed storage across multiple nodes (when available)

Command Line Options
--------------------

The Kademlia demo supports several command line options for customization:

.. code-block:: console

    $ python kademlia.py --help
    usage: kademlia.py [-h] [--mode MODE] [--port PORT] [--bootstrap [BOOTSTRAP ...]] [--verbose]

    Kademlia DHT example with content server functionality

    options:
      -h, --help            show this help message and exit
      --mode MODE           Run as a server or client node (default: server)
      --port PORT           Port to listen on (0 for random) (default: 0)
      --bootstrap [BOOTSTRAP ...]
                            Multiaddrs of bootstrap nodes. Provide a space-separated list of addresses.
                            This is required for client mode.
      --verbose             Enable verbose logging

**Examples:**

Start server on a specific port:

.. code-block:: console

    $ python kademlia.py --mode server --port 8000

Start client with verbose logging:

.. code-block:: console

    $ python kademlia.py --mode client --verbose

Connect to multiple bootstrap nodes:

.. code-block:: console

    $ python kademlia.py --mode client --bootstrap /ip4/127.0.0.1/tcp/8000/p2p/... /ip4/127.0.0.1/tcp/8001/p2p/...

How It Works
------------

The Kademlia DHT implementation demonstrates several key concepts:

**Server Mode:**
  - Stores key-value pairs in the distributed hash table
  - Advertises itself as a content provider for specific content
  - Handles incoming DHT requests from other nodes
  - Maintains routing table with known peers

**Client Mode:**
  - Connects to bootstrap nodes to join the network
  - Retrieves values by their keys from the DHT
  - Discovers content providers for specific content
  - Performs network lookups using the Kademlia algorithm

**Key Components:**
  - **Routing Table**: Organizes peers in k-buckets based on XOR distance
  - **Value Store**: Manages key-value storage with TTL (time-to-live)
  - **Provider Store**: Tracks which peers provide specific content
  - **Peer Routing**: Implements iterative lookups to find closest peers

The full source code for this example is below:

.. literalinclude:: ../examples/kademlia/kademlia.py
    :language: python
    :linenos:
