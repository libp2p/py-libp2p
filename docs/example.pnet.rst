Ping Demo
=========

This example demonstrates how to use the libp2p ``pnet`` with ping protocol.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ ping-demo -psk 1
    Run this from the same folder in another console:

    ping-demo -p 8001 -d /ip4/127.0.0.1/tcp/8000/p2p/QmXfptdHU6hqG95JswxYVUH4bphcK8y18mhFcgUQFe6fCN -psk 1

    Waiting for incoming connection...

Copy the line that starts with ``ping-demo -p 8001``, open a new terminal in the same
folder and paste it in:

.. code-block:: console

    $ ping-demo -p 8001 -d /ip4/127.0.0.1/tcp/8000/p2p/QmXfptdHU6hqG95JswxYVUH4bphcK8y18mhFcgUQFe6fCN -psk 1
    sending ping to QmXfptdHU6hqG95JswxYVUH4bphcK8y18mhFcgUQFe6fCN
    received pong from QmXfptdHU6hqG95JswxYVUH4bphcK8y18mhFcgUQFe6fCN

The full source code for this example is below:

.. literalinclude:: ../examples/ping/ping.py
    :language: python
    :linenos:
