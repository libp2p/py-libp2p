QUIC Echo Demo
==============

This example demonstrates a simple ``echo`` protocol using **QUIC transport**.

QUIC provides built-in TLS security and stream multiplexing over UDP, making it an excellent transport choice for libp2p applications.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ echo-quic-demo
    Run this from the same folder in another console:

    echo-quic-demo -d /ip4/127.0.0.1/udp/8000/quic-v1/p2p/16Uiu2HAmAsbxRR1HiGJRNVPQLNMeNsBCsXT3rDjoYBQzgzNpM5mJ

    Waiting for incoming connection...

Copy the line that starts with ``echo-quic-demo -p 8001``, open a new terminal in the same
folder and paste it in:

.. code-block:: console

    $ echo-quic-demo -d /ip4/127.0.0.1/udp/8000/quic-v1/p2p/16Uiu2HAmE3N7KauPTmHddYPsbMcBp2C6XAmprELX3YcFEN9iXiBu

    I am 16Uiu2HAmE3N7KauPTmHddYPsbMcBp2C6XAmprELX3YcFEN9iXiBu
    STARTING CLIENT CONNECTION PROCESS
    CLIENT CONNECTED TO SERVER
    Sent: hi, there!
    Got: ECHO: hi, there!

**Key differences from TCP Echo:**

- Uses UDP instead of TCP: ``/udp/8000`` instead of ``/tcp/8000``
- Includes QUIC protocol identifier: ``/quic-v1`` in the multiaddr
- Built-in TLS security (no separate security transport needed)
- Native stream multiplexing over a single QUIC connection

.. literalinclude:: ../examples/echo/echo_quic.py
    :language: python
    :linenos:
