GossipSub 1.2 Protocol Support
==============================

Overview
--------

Py-libp2p now supports the GossipSub 1.2 protocol specification, which introduces significant improvements for bandwidth efficiency and network performance. This document provides comprehensive information about the new features, configuration options, and best practices.

What's New in GossipSub 1.2
----------------------------

GossipSub 1.2 introduces several key improvements over previous versions:

* **IDONTWANT Control Messages**: A new mechanism to inform peers not to send specific messages, reducing unnecessary bandwidth usage
* **Enhanced Protocol ID**: Uses `/meshsub/1.2.0` protocol identifier
* **Backward Compatibility**: Maintains full compatibility with GossipSub 1.1 and earlier versions
* **Improved Memory Management**: Better handling of message tracking and cleanup

IDONTWANT Control Messages
--------------------------

The most significant feature in GossipSub 1.2 is the introduction of IDONTWANT control messages. These messages allow peers to inform each other about messages they have already received, preventing duplicate message transmission and improving overall network efficiency.

How IDONTWANT Works
~~~~~~~~~~~~~~~~~~~

1. **Message Reception**: When a peer receives a message, it can send an IDONTWANT control message to its mesh peers
2. **Bandwidth Optimization**: Mesh peers will avoid sending the same message to the peer that sent the IDONTWANT
3. **Memory Management**: The system tracks IDONTWANT messages with configurable limits to prevent memory exhaustion

Performance Benefits
~~~~~~~~~~~~~~~~~~~~

IDONTWANT messages provide the most benefit in scenarios with:

* **Large Messages**: Significant bandwidth savings when preventing duplicate large message transmission
* **High-Frequency Messaging**: Reduces network congestion in busy pubsub topics
* **Mesh Networks**: Particularly effective in well-connected mesh topologies

Configuration Options
---------------------

GossipSub 1.2 introduces new configuration parameters to control IDONTWANT behavior:

max_idontwant_messages
~~~~~~~~~~~~~~~~~~~~~~

**Default Value**: 10

**Purpose**: Limits the number of message IDs tracked per peer in IDONTWANT lists to prevent memory exhaustion from malicious or misbehaving peers.

**DoS Prevention**: This parameter is crucial for preventing denial-of-service attacks where peers might send excessive IDONTWANT messages to consume memory resources.

**Rationale for Default Value**: The default value of 10 was chosen based on:
- Analysis of typical message patterns in pubsub networks
- Balance between memory usage and bandwidth optimization
- Protection against potential DoS attacks
- Compatibility with existing network topologies

**Performance Implications**:
- **Small Messages**: IDONTWANT overhead may exceed benefits for very small messages
- **Large Messages**: Significant bandwidth savings for messages larger than typical IDONTWANT control message size
- **High-Frequency Scenarios**: Most beneficial when message frequency is high

Memory Management
-----------------

GossipSub 1.2 implements aggressive cleanup of IDONTWANT entries during heartbeat intervals to prevent memory leaks.

Current Approach
~~~~~~~~~~~~~~~~

The current implementation uses aggressive cleanup (clears all entries) which provides:

* **Simplicity**: Easy to understand and maintain
* **Memory Safety**: Strong guarantees against memory leaks
* **Suitable for Regular Heartbeats**: Works well for applications with consistent heartbeat intervals

Alternative Approaches
~~~~~~~~~~~~~~~~~~~~~~

The JavaScript implementation uses time-based expiration, which offers:

* **More Sophisticated**: Tracks timestamps and only clears expired entries
* **Better for Long-Running Applications**: More efficient for applications with infrequent heartbeats
* **Future Enhancement**: Could be considered for GossipSub v1.3+ or as a separate optimization

Usage Examples
--------------

Basic GossipSub 1.2 Setup
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from libp2p import new_node
    from libp2p.pubsub.gossipsub import GossipSub
    from libp2p.pubsub.pubsub import PubSub

    # Create a new libp2p node
    node = await new_node()

    # Initialize GossipSub with default settings
    gossipsub = GossipSub()

    # Initialize PubSub with GossipSub
    pubsub = PubSub(gossipsub)

    # Start the node
    await node.start()

Custom Configuration
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from libp2p.pubsub.gossipsub import GossipSub

    # Configure GossipSub with custom IDONTWANT limits
    gossipsub = GossipSub(
        max_idontwant_messages=20,  # Allow more IDONTWANT messages per peer
        # ... other parameters
    )

Protocol Compatibility
----------------------

GossipSub 1.2 maintains full backward compatibility:

* **Protocol Negotiation**: Automatically negotiates the highest supported version
* **Graceful Degradation**: Falls back to GossipSub 1.1 if peers don't support 1.2
* **Mixed Networks**: Supports networks with both 1.1 and 1.2 peers

Migration Guide
---------------

Upgrading from GossipSub 1.1 to 1.2 is straightforward:

1. **No Code Changes Required**: Existing applications work without modification
2. **Automatic Protocol Detection**: The system automatically uses 1.2 when available
3. **Configuration Optional**: Default settings work for most use cases
4. **Performance Benefits**: Immediate bandwidth improvements in compatible networks

Best Practices
--------------

Configuration Recommendations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Default Settings**: Start with default configuration unless you have specific requirements
* **Monitor Memory Usage**: Keep an eye on memory consumption in long-running applications
* **Network Analysis**: Consider your message size and frequency patterns when tuning parameters
* **Security Considerations**: Be aware of potential DoS vectors and configure limits appropriately

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

* **Message Size**: IDONTWANT is most beneficial for messages larger than ~1KB
* **Network Topology**: Works best in well-connected mesh networks
* **Heartbeat Frequency**: Regular heartbeats ensure proper cleanup of IDONTWANT entries
* **Peer Management**: Monitor peer behavior for excessive IDONTWANT usage

Troubleshooting
---------------

Common Issues
~~~~~~~~~~~~~

**High Memory Usage**
- Check if `max_idontwant_messages` is set too high
- Monitor for peers sending excessive IDONTWANT messages
- Consider reducing the limit if memory usage is a concern

**Network Performance**
- Verify that peers support GossipSub 1.2
- Check network topology and connectivity
- Monitor message sizes and frequency patterns

**Compatibility Issues**
- Ensure all peers are using compatible libp2p versions
- Check protocol negotiation logs
- Verify network configuration and firewall settings

Specification References
------------------------

* `GossipSub v1.2 Specification <https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/gossipsub-v1.2.md>`_
* `libp2p PubSub Specification <https://github.com/libp2p/specs/blob/master/pubsub/README.md>`_
* `Py-libp2p GossipSub API Documentation <libp2p.pubsub.gossipsub>`_

Related Documentation
---------------------

* :doc:`examples.pubsub` - Practical examples using GossipSub
* :doc:`libp2p.pubsub` - Complete PubSub API documentation
* :doc:`getting_started` - Getting started with Py-libp2p
