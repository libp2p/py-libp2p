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

   import trio
   import multiaddr
   from libp2p import new_host
   from libp2p.crypto.keys import create_new_key_pair
   from libp2p.security.tls.transport import TLSTransport, PROTOCOL_ID

   async def main():
       # Create a key pair for the host
       key_pair = create_new_key_pair()
       
       # Create TLS transport with the key pair
       tls_transport = TLSTransport(key_pair)
       
       # Create security options mapping
       sec_opt = {PROTOCOL_ID: tls_transport}
       
       # Create host with TLS security option
       host = new_host(key_pair=key_pair, sec_opt=sec_opt)
       
       # Create Multiaddr object for listening
       listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/8000")
       
       # Run the host and listen
       async with host.run(listen_addrs=[listen_addr]):
           print("TLS-enabled listener at:", host.get_addrs())
           await trio.sleep_forever()

   if __name__ == "__main__":
       trio.run(main())

Dialer node:

.. code-block:: python

   import trio
   import multiaddr
   from libp2p import new_host
   from libp2p.crypto.keys import create_new_key_pair
   from libp2p.security.tls.transport import TLSTransport, PROTOCOL_ID
   from libp2p.peer.peerinfo import info_from_p2p_addr

   async def main():
       # Create a key pair for the host
       key_pair = create_new_key_pair()
       
       # Create TLS transport with the key pair
       tls_transport = TLSTransport(key_pair)
       
       # Create security options mapping
       sec_opt = {PROTOCOL_ID: tls_transport}
       
       # Create host with TLS security option
       host = new_host(key_pair=key_pair, sec_opt=sec_opt)
       
       # Parse the listener address (replace with actual listener address)
       addr = "/ip4/127.0.0.1/tcp/8000/p2p/QmPeerIDHere"
       maddr = multiaddr.Multiaddr(addr)
       peer_info = info_from_p2p_addr(maddr)
       
       # Run the host and connect
       async with host.run():
           await host.connect(peer_info)
           print("Connected securely to", peer_info.peer_id)
           await trio.sleep(1)

   if __name__ == "__main__":
       trio.run(main())

**Defaults if no configuration is provided**

- Generates a self-signed certificate automatically.

**Note for testing with self-signed certificates**

When testing with self-signed certificates, peers need to trust each other's certificates.
You can do this by calling ``trust_peer_cert_pem()`` on the TLS transport before creating the host:

.. code-block:: python

   # For testing: trust peer certificates
   listener_tls.trust_peer_cert_pem(dialer_tls.get_certificate_pem())
   dialer_tls.trust_peer_cert_pem(listener_tls.get_certificate_pem())

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
