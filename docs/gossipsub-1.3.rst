GossipSub 1.3 Extensions and Topic Observation
==============================================

Overview
--------

Py-libp2p supports the GossipSub v1.3 Extensions Control Message mechanism and the
Topic Observation extension. These features require negotiating the
``/meshsub/1.3.0`` protocol (or later) with peers.

Topic Observation
-----------------

The Topic Observation extension allows a peer to receive IHAVE notifications for
a topic without being a full subscriber. This is useful for presence awareness:
knowing when messages are published on a topic without actually receiving the
message payloads.

Lifecycle
~~~~~~~~~

1. **Start observing**: Call ``start_observing_topic(topic)`` to send OBSERVE
   control messages to in-topic peers that support the extension. The router
   will then send IHAVE notifications to you when new messages arrive on that
   topic.

2. **Receive IHAVE**: As an observer, you receive IHAVE control messages
   containing message IDs. These are presence notifications only; observers do
   not typically reply with IWANT to fetch the actual messages.

3. **Stop observing**: Call ``stop_observing_topic(topic)`` to send UNOBSERVE
   control messages and stop receiving IHAVE notifications for that topic.

Usage Example
~~~~~~~~~~~~~

.. code-block:: python

    from libp2p import new_node
    from libp2p.pubsub.gossipsub import GossipSub
    from libp2p.pubsub.pubsub import Pubsub

    # Create node with GossipSub v1.3
    node = await new_node()
    gossipsub = GossipSub()  # Default config includes v1.3 protocols
    pubsub = PubSub(gossipsub)
    await node.start()
    pubsub.set_pubsub(node)

    # Start observing a topic (no subscription; IHAVE-only notifications)
    await gossipsub.start_observing_topic("my-topic")

    # ... later, when done ...
    await gossipsub.stop_observing_topic("my-topic")

Protocol Requirements
~~~~~~~~~~~~~~~~~~~~~

* Topic Observation requires both peers to negotiate ``/meshsub/1.3.0`` (or
  later) and to advertise support via the Extensions Control Message.
* Extensions are only sent when the negotiated protocol is v1.3+; peers on
  v1.1/v1.2 do not receive extension fields.

Specification References
------------------------

* `GossipSub v1.3 Extensions <https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/gossipsub-v1.3.md>`_
* `Topic Observation proposal <https://ethresear.ch/t/gossipsub-topic-observation-proposed-gossipsub-1-3/20907>`_

Related Documentation
---------------------

* :doc:`gossipsub-1.2` - GossipSub 1.2 features (IDONTWANT, etc.)
* :doc:`examples.pubsub` - PubSub chat example
* :doc:`libp2p.pubsub` - Complete PubSub API documentation
