
PubSub Chat Demo
================

This example demonstrates how to create a chat application using libp2p's PubSub implementation with the GossipSub protocol.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ pubsub-demo
    Node started with peer ID: QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N
    Listening on: /ip4/127.0.0.1/tcp/12345
    Initializing PubSub and GossipSub...
    Pubsub and GossipSub services started.
    Pubsub ready.
    Subscribed to topic: pubsub-chat
    Run this script in another console with:
    pubsub-demo -d /ip4/127.0.0.1/tcp/12345/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N

    Waiting for peers...
    Type messages to send (press Enter to send):

Copy the line that starts with ``pubsub-demo -d``, open a new terminal and paste it in:

.. code-block:: console

    $ pubsub-demo -d /ip4/127.0.0.1/tcp/12345/p2p/QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N
    Node started with peer ID: QmXZLbpYC9vRmMDcMVmzey7wGnZBWWPv4UYh3G5UzLnTMf
    Listening on: /ip4/127.0.0.1/tcp/54321
    Initializing PubSub and GossipSub...
    Pubsub and GossipSub services started.
    Pubsub ready.
    Subscribed to topic: pubsub-chat
    Connecting to peer: QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N using protocols: [Protocol(code=4, name='ip4', path=False, size=32), Protocol(code=6, name='tcp', path=False, size=16), Protocol(code=421, name='p2p', path=False, size=-1)]
    Run this script in another console with:
    pubsub-demo -d /ip4/127.0.0.1/tcp/54321/p2p/QmXZLbpYC9vRmMDcMVmzey7wGnZBWWPv4UYh3G5UzLnTMf

    Connected to peer: QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N
    Type messages to send (press Enter to send):

You can then start typing messages in either terminal and see them relayed to the other terminal. The messages will be distributed using the GossipSub protocol to all peers subscribed to the same topic. To exit the demo, type "quit" or send a keyboard interrupt (``Ctrl+C``) in either terminal.

Command Line Options
--------------------

- ``-t, --topic``: Specify the topic name to subscribe to (default: "pubsub-chat")
- ``-d, --destination``: Address of peer to connect to
- ``-p, --port``: Port to listen on (default: random available port)
- ``-v, --verbose``: Enable debug logging

The full source code for this example is below:

.. literalinclude:: ../examples/pubsub/pubsub.py
    :language: python
    :linenos:
