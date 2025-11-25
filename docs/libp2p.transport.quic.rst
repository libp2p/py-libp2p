libp2p.transport.quic package
=============================

Connection ID Management
------------------------

The QUIC transport implementation uses a sophisticated Connection ID (CID) management system
inspired by the `quinn` Rust QUIC library. This system ensures proper packet routing and
handles connection migration scenarios.

Key Features
~~~~~~~~~~~~

**Sequence Number Tracking**
   Each Connection ID is assigned a sequence number, starting at 0 for the initial CID.
   Sequence numbers are used to ensure proper retirement ordering per the QUIC specification.

**Initial vs. Established CIDs**
   Initial CIDs (used during handshake) are tracked separately from established connection CIDs.
   This separation allows for efficient packet routing and proper handling of handshake packets.

**Fallback Routing**
   When packets arrive with new Connection IDs before ``ConnectionIdIssued`` events are processed,
   the system uses O(1) fallback routing based on address mappings. This handles race conditions
   gracefully and ensures packets are routed correctly.

**Retirement Ordering**
   Connection IDs are retired in sequence order, ensuring compliance with the QUIC specification.
   The ``ConnectionIDRegistry`` maintains sequence number mappings to enable proper retirement.

Architecture
~~~~~~~~~~~~

The ``ConnectionIDRegistry`` class manages all Connection ID routing state:

- **Established connections**: Maps Connection IDs to ``QUICConnection`` instances
- **Pending connections**: Maps Connection IDs to ``QuicConnection`` (aioquic) instances during handshake
- **Initial CIDs**: Separate tracking for handshake packet routing
- **Sequence tracking**: Maps Connection IDs to sequence numbers and connections to sequence ranges
- **Address mappings**: Bidirectional mappings between Connection IDs and addresses for O(1) fallback routing

Performance Monitoring
~~~~~~~~~~~~~~~~~~~~~~

The registry tracks performance metrics including:

- Fallback routing usage count
- Sequence number distribution
- Operation timings (when debug mode is enabled)

These metrics can be accessed via the ``get_stats()`` method and reset using ``reset_stats()``.

Submodules
----------

libp2p.transport.quic.config module
-----------------------------------

.. automodule:: libp2p.transport.quic.config
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.transport.quic.connection module
---------------------------------------

.. automodule:: libp2p.transport.quic.connection
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.transport.quic.exceptions module
---------------------------------------

.. automodule:: libp2p.transport.quic.exceptions
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.transport.quic.listener module
-------------------------------------

.. automodule:: libp2p.transport.quic.listener
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.transport.quic.security module
-------------------------------------

.. automodule:: libp2p.transport.quic.security
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.transport.quic.stream module
-----------------------------------

.. automodule:: libp2p.transport.quic.stream
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.transport.quic.transport module
--------------------------------------

.. automodule:: libp2p.transport.quic.transport
   :members:
   :undoc-members:
   :show-inheritance:

libp2p.transport.quic.utils module
----------------------------------

.. automodule:: libp2p.transport.quic.utils
   :members:
   :undoc-members:
   :show-inheritance:

Module contents
---------------

.. automodule:: libp2p.transport.quic
   :members:
   :undoc-members:
   :show-inheritance:
