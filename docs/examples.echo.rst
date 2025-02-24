Echo Demo
=========

This example demonstrates a simple ``echo`` protocol.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ echo-demo
    Run this from the same folder in another console:

    echo-demo -p 8001 -d /ip4/127.0.0.1/tcp/8000/p2p/16Uiu2HAmAsbxRR1HiGJRNVPQLNMeNsBCsXT3rDjoYBQzgzNpM5mJ

    Waiting for incoming connection...

Copy the line that starts with ``echo-demo -p 8001``, open a new terminal in the same
folder and paste it in:

.. code-block:: console

    $ echo-demo -p 8001 -d /ip4/127.0.0.1/tcp/8000/p2p/16Uiu2HAmAsbxRR1HiGJRNVPQLNMeNsBCsXT3rDjoYBQzgzNpM5mJ

    I am 16Uiu2HAmE3N7KauPTmHddYPsbMcBp2C6XAmprELX3YcFEN9iXiBu
    Sent: hi, there!

    Got: hi, there!

.. literalinclude:: ../examples/echo/echo.py
    :language: python
    :linenos:
