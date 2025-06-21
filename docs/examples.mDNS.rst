mDNS Peer Discovery Example
===========================

This example demonstrates how to use mDNS (Multicast DNS) for peer discovery in py-libp2p.

Prerequisites
-------------

First, ensure you have py-libp2p installed and your environment is activated:

.. code-block:: console

    $ python -m pip install libp2p

Running the Example
-------------------

The mDNS demo script allows you to discover peers on your local network using mDNS. To start a peer, run:

.. code-block:: console

    $ mdns-demo

You should see output similar to:

.. code-block:: console

    Run this from another console to start another peer on a different port:

    python mdns-demo -p <ANOTHER_PORT>

    Waiting for mDNS peer discovery events...

    2025-06-20 23:28:12,052 - libp2p.example.discovery.mdns - INFO - Starting peer Discovery

To discover peers, open another terminal and run the same command with a different port:

.. code-block:: console

    $ python mdns-demo -p 9001

You should see output indicating that a new peer has been discovered:

.. code-block:: console

    Run this from the same folder in another console to start another peer on a different port:

    python mdns-demo -p <ANOTHER_PORT>

    Waiting for mDNS peer discovery events...

    2025-06-20 23:43:43,786 - libp2p.example.discovery.mdns - INFO - Starting peer Discovery
    2025-06-20 23:43:43,790 - libp2p.example.discovery.mdns - INFO - Discovered: 16Uiu2HAmGxy5NdQEjZWtrYUMrzdp3Syvg7MB2E5Lx8weA9DanYxj

When a new peer is discovered, its peer ID will be printed in the console output.

How it Works
------------

- Each node advertises itself on the local network using mDNS.
- When a new peer is discovered, the handler prints its peer ID.
- This is useful for local peer discovery without requiring a DHT or bootstrap nodes.

You can modify the script to perform additional actions when peers are discovered, such as opening streams or exchanging messages.
