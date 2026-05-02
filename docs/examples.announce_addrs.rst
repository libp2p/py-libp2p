Announce Addresses
==================

This example demonstrates how to use announce addresses so that a node behind
NAT or a reverse proxy (e.g., ngrok) advertises its publicly reachable address
instead of its local listen address.

When running a libp2p node behind NAT or a reverse proxy, other nodes cannot
reach it using the internal listen address.  By specifying announce addresses,
you can tell peers about your externally accessible addresses instead.

Usage
-----

First, ensure you have installed the necessary dependencies from the root of
the repository:

.. code-block:: console

    $ python -m pip install -e .

**Node A (listener)** -- start the listener with announce addresses:

.. code-block:: console

    $ python examples/announce_addrs/announce_addrs.py --listen-port 9001 \
        --announce /dns4/example.ngrok-free.app/tcp/9001 /ip4/1.2.3.4/tcp/4001

**Node B (dialer)** -- connect to the listener using its announced address and
peer ID:

.. code-block:: console

    $ python examples/announce_addrs/announce_addrs.py --listen-port 9002 \
        --dial /dns4/example.ngrok-free.app/tcp/9001/p2p/<PEER_ID_OF_A>

Notes on NAT and Reverse Proxies
--------------------------------

This pattern is useful when:

- Your node is behind a NAT that performs port forwarding from an external IP
  to your local machine.
- You are using a reverse proxy like ngrok that exposes your local port to the
  internet.
- You need to advertise different addresses for external vs. internal
  connectivity.

By announcing the correct external addresses, peers will successfully dial your
node regardless of their network position.

The full source code for this example is below:

.. literalinclude:: ../examples/announce_addrs/announce_addrs.py
    :language: python
    :linenos:
