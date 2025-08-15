TLS Support in py-libp2p
=========================

Transport Layer Security (TLS) provides encrypted communication and peer authentication in py-libp2p, ensuring:

- **Data confidentiality**: Prevents eavesdropping
- **Integrity protection**: Detects tampering
- **Peer authentication**: Verifies identities via certificates

TLS in libp2p Security Stack
============================
- Operates at the **transport security layer** (alongside Noise protocol)
- Complies with libp2p's `SECIO <https://docs.libp2p.io/concepts/security/secio/>`_ replacement initiative
- Current implementation status: **Stable** (interoperable with go-libp2p/js-libp2p)

--------------------------
2. Installation Requirements
--------------------------

Python Dependencies
===================
.. code-block:: bash

   pip install py-libp2p[tls]  # Installs with TLS extras

Mandatory:
- ``cryptography`` >= 3.4
- ``pyOpenSSL`` >= 20.0

Platform Support
================
- **OS**: Linux/macOS/Windows (with OpenSSL)
- **Python**: 3.8+
- **OpenSSL**: 1.1.1 or newer

----------------------------
3. Enabling TLS in py-libp2p
----------------------------

Basic Configuration
===================
.. code-block:: python

   from libp2p import new_node
   from libp2p.security.tls.transport import TLSTransport

   async def create_tls_node():
       node = await new_node(
           security_transports=[TLSTransport()],  # Explicit TLS enable
           transport_priority=['/tls/1.0.0']     # Prefer TLS over other security layers
       )
       await node.listen("/ip4/0.0.0.0/tcp/8000")
       print(f"Node ID: {node.get_id()}, Listening on: {node.get_addrs()}")

Default Behavior
================
- TLS **enabled by default** in py-libp2p >= 0.3.0
- Auto-generates self-signed certificates if none provided
- Fallback to Noise protocol if TLS handshake fails

------------------------
4. Certificate Management
------------------------

Generating Certificates
=======================
For development (self-signed):

.. code-block:: bash

   openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

Production Recommendations
==========================
- Use **CA-signed certificates** for public nodes
- Store keys in secure vaults (Hashicorp Vault/AWS Secrets Manager)
- Implement certificate rotation:

.. code-block:: python

   TLSTransport(
       identity_loader=my_cert_rotation_func  # Callable returning (cert, key)
   )

----------------------------
5. Testing TLS Connections
----------------------------

Local Test Between Python Nodes
===============================
1. Start listener:

.. code-block:: python

   node1 = await new_node(security_transports=[TLSTransport()])
   await node1.listen("/ip4/0.0.0.0/tcp/8000")

2. Connect from second node:

.. code-block:: python

   stream = await node2.dial(node1.get_id(), "/tls/1.0.0")
   assert stream.is_encrypted()

Interop Testing Matrix
=======================
+----------------+----------------+----------------+
| Implementation | Handshake      | Data Transfer  |
+================+================+================+
| py-libp2p      | ✅             | ✅             |
+----------------+----------------+----------------+
| go-libp2p      | ✅ (v0.23+)    | ✅             |
+----------------+----------------+----------------+
| js-libp2p      | ✅ (v0.42+)    | ✅             |
+----------------+----------------+----------------+

Debugging Tips
==============
Enable verbose logging:

.. code-block:: python

   import logging
   logging.basicConfig(level=logging.DEBUG)

--------------------------------
6. Security Considerations
--------------------------------

Critical Configuration Checks
=============================
- Verify ``peer_id`` matches certificate hash
- Disable deprecated TLS versions:

.. code-block:: python

   TLSTransport(
       tls_min_version=ssl.TLSVersion.TLSv1_3
   )

Threat Model
============
- Mitigates: MITM attacks, replay attacks
- Does **not** protect against: DDoS, protocol-level exploits

Roadmap
=======
- QUIC integration (Q2 2024)
- Post-quantum cryptography (Q3 2024)

------------------------
7. Troubleshooting
------------------------

Common Errors
=============
``TLS handshake failed``
  - Cause: Clock skew >5 minutes
  - Fix: Sync system time

``UnknownProtocolError``
  - Cause: Mismatched ``/tls`` version
  - Fix: Update both nodes to same libp2p version

Debugging Commands
==================
Verify certificate chain:

.. code-block:: bash

   openssl s_client -connect 127.0.0.1:8000 -showcerts

```

