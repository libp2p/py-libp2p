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
  from libp2p.crypto.secp256k1 import create_new_key_pair
  from libp2p.security.tls.transport import PROTOCOL_ID, TLSTransport

  async def main():
    key_pair = create_new_key_pair(secret=None)
    tls_transport = TLSTransport(libp2p_keypair=key_pair)
    sec_opt = {PROTOCOL_ID: tls_transport}
    host = new_host(key_pair=key_pair, sec_opt=sec_opt)
    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/8000")
    async with host.run(listen_addrs=[listen_addr]):
        while not host.get_addrs():
            await trio.sleep(0.1)
        addrs = host.get_addrs()
        peer_id = host.get_id()
        print("TLS-enabled listener at:", addrs[0] if addrs else "No addresses")
        print("Peer ID:", peer_id)
        print("\nUse this address with the dialer:")
        print(f"  /ip4/127.0.0.1/tcp/8000/p2p/{peer_id}")
        await trio.sleep_forever()

  if __name__ == "__main__":
    trio.run(main)

Dialer node:

.. code-block:: python

  import trio
  import multiaddr
  from libp2p import new_host
  from libp2p.crypto.secp256k1 import create_new_key_pair
  from libp2p.security.tls.transport import PROTOCOL_ID, TLSTransport
  from libp2p.peer.peerinfo import info_from_p2p_addr

  async def main():
      key_pair = create_new_key_pair(secret=None)
      tls_transport = TLSTransport(libp2p_keypair=key_pair)
      sec_opt = {PROTOCOL_ID: tls_transport}
      host = new_host(key_pair=key_pair, sec_opt=sec_opt)

      addr = "/ip4/127.0.0.1/tcp/8000/p2p/16Uiu2HAm3hATVnBDT13acn2utRJXsFa2LRRGrZwDsosJ1mFZsM2Q"
      maddr = multiaddr.Multiaddr(addr)
      peer_info = info_from_p2p_addr(maddr)

      async with host.run(listen_addrs=[]):
          await trio.sleep(0.5)
          host.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 120)

          try:
              await host.connect(peer_info)
              print("Connected securely to", peer_info.peer_id)
              await trio.sleep(1)
          except Exception as e:
              print(f"Connection failed: {e}")
              raise

  if __name__ == "__main__":
      trio.run(main)

**Defaults if no configuration is provided**

- Generates a self-signed certificate automatically.

**Note for testing with self-signed certificates**

When testing with self-signed certificates in unit tests or demos, peers may call
``trust_peer_cert_pem()`` to preload a peer cert into the OpenSSL trust store.
Production interop does **not** require this: identity is verified via the
libp2p X.509 extension after the handshake (same model as go-libp2p and
js-libp2p).

.. code-block:: python

   # Optional for tests/demos only: PKIX trust store workaround
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

Mutual authentication (inbound)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Inbound TLS connections **must** present a client certificate that carries the
libp2p X.509 extension so py-libp2p can derive and verify the remote Peer ID.
The server requests a client certificate during the TLS handshake; post-handshake
logic enforces the requirement via the libp2p extension (not PKIX CA trust). If
the remote peer completes the TLS handshake without sending a certificate, the
connection is rejected and no ``SecureSession`` is created.

**AutoTLS exception:** When ``enable_autotls=True``, broker registration may
use the primitive key-exchange side-channel or a placeholder identity instead
of a libp2p client certificate. This path is scoped exclusively to the
AutoTLS bootstrap flow and is not reachable on a standard node.

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
   * - Inbound connection rejected / handshake failure
     - Remote peer sent no client certificate
     - Ensure the dialer uses libp2p TLS with an identity certificate; do not connect with a plain TLS client.
   * - Connection refused
     - Port blocked or listener not running
     - Check firewall rules and listener status.
