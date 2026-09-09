Interoperability Testing
========================

This example provides a standalone console script for testing libp2p ping functionality
without Docker or Redis dependencies. It supports both listener and dialer roles and
measures ping RTT and handshake times.

Usage
-----

Run as listener (waits for connection):

.. code-block:: console

    $ python -m examples.interop.local_ping_test --listener --port 8000
    Listener ready, listening on:
      /ip4/127.0.0.1/tcp/8000/p2p/Qm...
    Waiting for dialer to connect...

Run as dialer (connects to listener):

.. code-block:: console

    $ python -m examples.interop.local_ping_test --dialer --destination /ip4/127.0.0.1/tcp/8000/p2p/Qm...
    Connecting to listener at: /ip4/127.0.0.1/tcp/8000/p2p/Qm...
    Connected successfully
    Performing ping test
    {"handshakePlusOneRTTMillis": 15.2, "pingRTTMilllis": 2.1}

Options
-------

- ``--listener``: Run as listener (wait for connection)
- ``--dialer``: Run as dialer (connect to listener)
- ``--destination ADDR``: Destination multiaddr (required for dialer)
- ``--port PORT``: Port number (0 = auto-select)
- ``--transport {tcp,ws,quic-v1}``: Transport protocol (default: tcp)
- ``--muxer {mplex,yamux}``: Stream muxer (default: mplex)
- ``--security {noise,plaintext}``: Security protocol (default: noise)
- ``--test-timeout SECONDS``: Test timeout in seconds (default: 180)
- ``--debug``: Enable debug logging

The full source code for this example is below:

.. literalinclude:: ../examples/interop/local_ping_test.py
    :language: python
    :linenos:
