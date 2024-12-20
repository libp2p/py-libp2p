Chat Demo
=========

This example demonstrates how to create a simple chat application using libp2p.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ chat-demo
    Run this from the same folder in another console:

    chat-demo -p 8001 -d /ip4/127.0.0.1/tcp/8000/p2p/QmPouApKqyxJDy6YT21EXNS6efuNzvJ3W3kqRQxkQ77GFJ

    Waiting for incoming connection...

Copy the line that starts with ``chat-demo -p 8001``, open a new terminal in the same
folder and paste it in:

.. code-block:: console

    $ chat-demo -p 8001 -d /ip4/127.0.0.1/tcp/8000/p2p/QmPouApKqyxJDy6YT21EXNS6efuNzvJ3W3kqRQxkQ77GFJ
    Connected to peer /ip4/127.0.0.1/tcp/8000

You can then start typing messages in either terminal and see them relayed to the
other terminal. To exit the demo, send a keyboard interrupt (``Ctrl+C``) in either terminal.

The full source code for this example is below:

.. literalinclude:: ../examples/chat/chat.py
    :language: python
    :linenos:
