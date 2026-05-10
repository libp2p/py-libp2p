
PubSub Chat Demo
================

This example demonstrates how to create a chat application using libp2p's PubSub implementation with the GossipSub protocol.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ pubsub-demo
    2025-04-06 23:59:17,471 - pubsub-demo - INFO - Running pubsub chat example...
    2025-04-06 23:59:17,471 - pubsub-demo - INFO - Your selected topic is: pubsub-chat
    2025-04-06 23:59:17,472 - pubsub-demo - INFO - Using random available port: 33269
    2025-04-06 23:59:17,490 - pubsub-demo - INFO - Node started with peer ID: QmcJnocH1d1tz3Zp4MotVDjNfNFawXHw2dpB9tMYGTXJp7
    2025-04-06 23:59:17,490 - pubsub-demo - INFO - Listening on: /ip4/127.0.0.1/tcp/33269
    2025-04-06 23:59:17,490 - pubsub-demo - INFO - Initializing PubSub and GossipSub...
    2025-04-06 23:59:17,491 - pubsub-demo - INFO - Pubsub and GossipSub services started.
    2025-04-06 23:59:17,491 - pubsub-demo - INFO - Pubsub ready.
    2025-04-06 23:59:17,491 - pubsub-demo - INFO - Subscribed to topic: pubsub-chat
    2025-04-06 23:59:17,491 - pubsub-demo - INFO - Run this script in another console with:
    pubsub-demo -d /ip4/127.0.0.1/tcp/33269/p2p/QmcJnocH1d1tz3Zp4MotVDjNfNFawXHw2dpB9tMYGTXJp7

    2025-04-06 23:59:17,491 - pubsub-demo - INFO - Waiting for peers...
    Type messages to send (press Enter to send):

Copy the line that starts with ``pubsub-demo -d``, open a new terminal and paste it in:

.. code-block:: console

    $ pubsub-demo -d /ip4/127.0.0.1/tcp/33269/p2p/QmcJnocH1d1tz3Zp4MotVDjNfNFawXHw2dpB9tMYGTXJp7
    2025-04-07 00:00:59,845 - pubsub-demo - INFO - Running pubsub chat example...
    2025-04-07 00:00:59,846 - pubsub-demo - INFO - Your selected topic is: pubsub-chat
    2025-04-07 00:00:59,846 - pubsub-demo - INFO - Using random available port: 51977
    2025-04-07 00:00:59,864 - pubsub-demo - INFO - Node started with peer ID: QmYQKCm95Ut1aXsjHmWVYqdaVbno1eKTYC8KbEVjqUaKaQ
    2025-04-07 00:00:59,864 - pubsub-demo - INFO - Listening on: /ip4/127.0.0.1/tcp/51977
    2025-04-07 00:00:59,864 - pubsub-demo - INFO - Initializing PubSub and GossipSub...
    2025-04-07 00:00:59,864 - pubsub-demo - INFO - Pubsub and GossipSub services started.
    2025-04-07 00:00:59,865 - pubsub-demo - INFO - Pubsub ready.
    2025-04-07 00:00:59,865 - pubsub-demo - INFO - Subscribed to topic: pubsub-chat
    2025-04-07 00:00:59,866 - pubsub-demo - INFO - Connecting to peer: QmcJnocH1d1tz3Zp4MotVDjNfNFawXHw2dpB9tMYGTXJp7 using protocols: MultiAddrKeys(<Multiaddr /ip4/127.0.0.1/tcp/33269/p2p/QmcJnocH1d1tz3Zp4MotVDjNfNFawXHw2dpB9tMYGTXJp7>)
    2025-04-07 00:00:59,866 - pubsub-demo - INFO - Run this script in another console with:
    pubsub-demo -d /ip4/127.0.0.1/tcp/51977/p2p/QmYQKCm95Ut1aXsjHmWVYqdaVbno1eKTYC8KbEVjqUaKaQ

    2025-04-07 00:00:59,881 - pubsub-demo - INFO - Connected to peer: QmcJnocH1d1tz3Zp4MotVDjNfNFawXHw2dpB9tMYGTXJp7
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


GossipSub Large Message Demo
============================

This example demonstrates one-shot large payload behavior using GossipSub.
It runs two peers: a receiver and a sender. The sender publishes one 500KB
message, and the receiver prints payload size plus end-to-end timing.

.. code-block:: console

    $ gossipsub-large-message-demo
    2026-05-10 10:10:00,000 - gossipsub-large-message-demo - INFO - Running receiver mode
    2026-05-10 10:10:00,010 - gossipsub-large-message-demo - INFO - Receiver ready with peer ID: Qm...
    2026-05-10 10:10:00,010 - gossipsub-large-message-demo - INFO - Topic: gossipsub-large-message
    2026-05-10 10:10:00,010 - gossipsub-large-message-demo - INFO - Run this in a second terminal to send 500KB:
    2026-05-10 10:10:00,010 - gossipsub-large-message-demo - INFO - gossipsub-large-message-demo -d /ip4/127.0.0.1/tcp/12345/p2p/Qm... -t gossipsub-large-message

Open a second terminal and run the printed command:

.. code-block:: console

    $ gossipsub-large-message-demo -d /ip4/127.0.0.1/tcp/12345/p2p/Qm... -t gossipsub-large-message
    2026-05-10 10:10:05,000 - gossipsub-large-message-demo - INFO - Running sender mode
    2026-05-10 10:10:05,200 - gossipsub-large-message-demo - INFO - Publishing 512000-byte payload to topic 'gossipsub-large-message'...
    2026-05-10 10:10:05,260 - gossipsub-large-message-demo - INFO - Publish completed in 60.00 ms

The receiver then prints confirmation and timing:

.. code-block:: console

    2026-05-10 10:10:05,300 - gossipsub-large-message-demo - INFO - Received payload: 512000 bytes on topic 'gossipsub-large-message' from Qm...
    2026-05-10 10:10:05,300 - gossipsub-large-message-demo - INFO - End-to-end elapsed time: 100.00 ms

Command Line Options
--------------------

- ``-t, --topic``: Topic name to use (default: ``gossipsub-large-message``)
- ``-d, --destination``: Receiver address for sender mode
- ``-p, --port``: Local listen port (default: random available port)
- ``-v, --verbose``: Enable debug logging

The full source code for this example is below:

.. literalinclude:: ../examples/pubsub/gossipsub_large_message.py
    :language: python
    :linenos:
