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

Security
~~~~~~~~

Inbound QUIC connections must present a TLS certificate containing the libp2p
extension so the remote peer identity can be established. Connections that complete
the QUIC/TLS handshake without a peer certificate, or whose identity cannot be
verified, are rejected before the application callback is invoked. The listener
``connections_rejected`` statistic is incremented when such connections are closed.

Production QUIC listeners should always use the transport's default security
manager; disabling ``_security_manager`` skips libp2p identity verification even
when a TLS certificate is present.

Post-quantum key exchange
~~~~~~~~~~~~~~~~~~~~~~~~~

From py-libp2p 0.8.3, QUIC connections use the hybrid post-quantum key exchange
``X25519MLKEM768`` whenever the remote peer supports it. There is nothing to configure.
The dialer offers the group in its TLS ClientHello, and the listener selects it when the
dialer offers it.

The group comes from aioquic, which added it in version 1.9.0. py-libp2p 0.8.3 requires
``aioquic>=1.9.1`` and sets no TLS groups of its own, so the installed aioquic decides
what is offered. To check an installation:

.. code-block:: console

    $ python -c "import aioquic; print(aioquic.__version__)"

A peer that does not support ``X25519MLKEM768`` still connects. aioquic keeps offering
X25519, P-256 and P-384, and the handshake then settles on one of those.

What this covers, and what it does not:

- The session keys are derived from both an X25519 exchange and an ML-KEM-768
  encapsulation, so recorded traffic stays confidential as long as one of the two holds.
  This is the protection against an attacker who stores traffic today to decrypt it with
  a future quantum computer.
- Peer authentication is unchanged. The TLS certificate and the libp2p identity key
  still use classical signatures, so this does not protect against an attacker who has
  a quantum computer at the time of the handshake.
- This section is about the QUIC transport only.

go-libp2p and rust-libp2p offer the same group on QUIC by default. On loopback, with
aioquic 1.9.0 and 1.9.1, py-libp2p selected ``X25519MLKEM768`` with go-libp2p v0.51.0
and rust-libp2p 0.57.1 as dialer and as listener; the method and results are in
`issue #1581 <https://github.com/libp2p/py-libp2p/issues/1581>`__.

``tests/core/transport/quic/test_post_quantum_key_exchange.py`` reads the TLS hello
messages from the wire and fails if a handshake between two py-libp2p peers stops
offering or selecting the group.

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
