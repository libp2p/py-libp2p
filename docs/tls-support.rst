Py-libp2p – TLS Support Documentation 
======================================================

.. contents::
   :depth: 2
   :local:

Overview of TLS in Libp2p
-------------------------

**Purpose of TLS in P2P networking**

- Encrypts data between peers.
- Authenticates peer identity using certificates.
- Prevents man-in-the-middle attacks.

**Integration in libp2p security modules**

- TLS is one of the supported secure channel protocols (alongside Noise).
- Negotiated during connection setup.

**Current status**

- **py-libp2p**: Experimental, usable for local and interop tests.
- **go-libp2p / js-libp2p**: Stable and production-ready.

Installation Requirements
-------------------------

**Python requirements**

- Python 3.8+

**Install with TLS support**

.. code-block:: bash

   pip install "libp2p[tls]"

**Additional dependencies**

Ubuntu / Debian:

.. code-block:: bash

   sudo apt install build-essential python3-dev libffi-dev libssl-dev

macOS:

.. code-block:: bash

   brew install openssl

Enabling TLS in py-libp2p
-------------------------

**Working example – Listener and Dialer**

Listener node:

.. code-block:: python

   import asyncio
   from libp2p import new_host
   from libp2p.security.tls.transport import TLSTransport

   async def main():
       host = await new_host(security_transports=[TLSTransport()])
       await host.listen("/ip4/0.0.0.0/tcp/8000")
       print("TLS-enabled listener at:", host.get_addrs())

       await asyncio.Future()  # Keep running

   if __name__ == "__main__":
       asyncio.run(main())

Dialer node:

.. code-block:: python

   import asyncio
   from libp2p import new_host
   from libp2p.security.tls.transport import TLSTransport
   from libp2p.peer.peerinfo import info_from_p2p_addr

   async def main():
       host = await new_host(security_transports=[TLSTransport()])

       addr = "/ip4/127.0.0.1/tcp/8000/p2p/QmPeerIDHere"
       peer_info = info_from_p2p_addr(addr)

       await host.connect(peer_info)
       print("Connected securely to", peer_info.peer_id)

   if __name__ == "__main__":
       asyncio.run(main())

**Defaults if no configuration is provided**

- Generates a self-signed certificate automatically.

Certificate Management
----------------------

**Generate a development certificate**

.. code-block:: bash

   openssl req -x509 -newkey rsa:2048 \
     -keyout key.pem -out cert.pem \
     -days 365 -nodes -subj "/CN=py-libp2p"

- Store keys outside version control.
- Rotate certificates every 90 days in production.

Testing TLS Connections
-----------------------

**Local test steps**

1. Run the listener example.
2. Start the dialer with the listener's multiaddress.
3. Confirm the secure connection in logs.

**Interop testing**

- Ensure both nodes advertise `/tls/1.0.0`.
- Peer IDs must match certificate public keys.

Security Considerations
-----------------------

- Never disable certificate verification in production.
- Use TLS 1.3 or later.
- Pin certificates for critical peers.

Troubleshooting
---------------

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Problem
     - Cause
     - Solution
   * - Certificate not trusted
     - Self-signed without trust store entry
     - Add cert to local trust store or disable verification **only** in testing.
   * - Protocol negotiation failed
     - One peer does not support `/tls/1.0.0`
     - Enable TLS on both peers or use Noise.
   * - SSL handshake failure
     - TLS version mismatch or clock skew
     - Enforce TLS 1.3, sync system clock.
   * - `ImportError: No module named libp2p.security.tls`
     - TLS extras not installed
     - Run `pip install "libp2p[tls]"`.
   * - Connection refused
     - Port blocked or listener not running
     - Check firewall rules and listener status.
```




