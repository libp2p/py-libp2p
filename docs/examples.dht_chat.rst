DHT Peer-ID Chat Demo
=====================

This example demonstrates **decentralized messaging with DHT bootstrap**
(issue `#880 <https://github.com/libp2p/py-libp2p/issues/880>`_): after a
one-time introduction into a KadDHT overlay, peers look each other up by
**Peer ID** and open a direct chat stream — without pasting full multiaddrs
for every messaging dial.

What this demonstrates
----------------------

- Messaging dApps often hardcode bootstrap / rendezvous servers just to find
  chat peers.
- With KadDHT, peers that already share an overlay can resolve
  ``PeerInfo`` via ``KadDHT.find_peer(peer_id)`` and then dial.
- The DHT is a **routing layer**, not magic: an empty routing table cannot
  resolve Peer IDs. You still need a one-time intro (``--bootstrap``
  multiaddr in this demo). After that, subsequent dials use Peer IDs only.

How discovery works
-------------------

1. **Intro (once):** Peer A starts with no ``--bootstrap``. Peers B and C
   dial A's multiaddr once to join the overlay and seed their routing tables.
2. **Lookup:** B runs ``lookup <C_peer_id>`` / ``connect <C_peer_id>``. The
   node calls ``KadDHT.find_peer`` and receives C's listen addresses from the
   DHT (typically via A, which knows both joiners).
3. **Chat:** B opens a ``/dht-chat/1.0.0`` stream to C and sends a message.

This is different from :doc:`examples.chat`, where every dial requires the
full destination multiaddr.

Quick start
-----------

Install and run from a checkout (or use the ``dht-chat-demo`` console script
after installing the package)::

    $ python -m examples.dht_chat.dht_chat --port 18001

Copy the printed ``--bootstrap`` multiaddr (loopback is fine on one machine)::

    $ python -m examples.dht_chat.dht_chat --port 18002 \
        --bootstrap /ip4/127.0.0.1/tcp/18001/p2p/<PEER_A_ID>

    $ python -m examples.dht_chat.dht_chat --port 18003 \
        --bootstrap /ip4/127.0.0.1/tcp/18001/p2p/<PEER_A_ID>

Then on peer B (Peer ID of C only — no multiaddr)::

    > lookup <PEER_C_ID>
    > msg <PEER_C_ID> hello

Walkthrough (live demo transcript)
----------------------------------

The following logs were captured from a real three-process run on one host.
Noisy internal DHT stream warnings were omitted for readability.

Phase 1 — start intro peer A
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Peer A starts with an empty DHT. Other peers will use its multiaddr once to
join the overlay.

.. code-block:: console

    $ python -m examples.dht_chat.dht_chat --port 18001
    INFO Started as intro peer (empty DHT until others --bootstrap here)

    === DHT Chat node ready ===
    Peer ID: 12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8
    Listening on:
      /ip4/127.0.0.1/tcp/18001/p2p/12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8
      ...

    Other peers can join the overlay with:
      dht-chat-demo --bootstrap /ip4/127.0.0.1/tcp/18001/p2p/12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8

Phase 2 — B and C join via ``--bootstrap``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

B and C dial A once. After this, they share a DHT overlay with A (and will
learn about each other through routing-table maintenance and FIND_NODE).

.. code-block:: console

    $ python -m examples.dht_chat.dht_chat --port 18002 \
        --bootstrap /ip4/127.0.0.1/tcp/18001/p2p/12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8
    INFO Connecting to intro peer 12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8
    INFO Joined DHT overlay via intro peer 12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8

    === DHT Chat node ready ===
    Peer ID: 12D3KooWLLjeAnSrVfC2CH1SYT1GMGPWvF5eJ2LVmpCAYsswsmN5
    ...

.. code-block:: console

    $ python -m examples.dht_chat.dht_chat --port 18003 \
        --bootstrap /ip4/127.0.0.1/tcp/18001/p2p/12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8
    INFO Connecting to intro peer 12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8
    INFO Joined DHT overlay via intro peer 12D3KooWPdi4NB7hkNaGVHKs1VhMvc6dXphLa1kpGPUzuoCn25Y8

    === DHT Chat node ready ===
    Peer ID: 12D3KooWDLGXNskEwn1tFPSSJisnbPh69sTu23VQot57ZEcQFTok
    ...

Phase 3 — B resolves C by Peer ID only
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

B does **not** paste C's multiaddr. ``lookup`` calls ``KadDHT.find_peer`` and
prints the addresses returned by the DHT.

.. code-block:: console

    > lookup 12D3KooWDLGXNskEwn1tFPSSJisnbPh69sTu23VQot57ZEcQFTok
    INFO Looking up 12D3KooWDLGXNskEwn1tFPSSJisnbPh69sTu23VQot57ZEcQFTok via KadDHT.find_peer ...
    INFO DHT found 12D3KooWDLGXNskEwn1tFPSSJisnbPh69sTu23VQot57ZEcQFTok with 6 addr(s)
    lookup ok: 12D3KooWDLGXNskEwn1tFPSSJisnbPh69sTu23VQot57ZEcQFTok
      /ip4/127.0.0.1/tcp/18003/p2p/12D3KooWDLGXNskEwn1tFPSSJisnbPh69sTu23VQot57ZEcQFTok
      ...

Phase 4 — send a chat message
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``msg`` dials if needed and opens ``/dht-chat/1.0.0``. C prints the inbound
message.

.. code-block:: console

    # on B
    > msg 12D3KooWDLGXNskEwn1tFPSSJisnbPh69sTu23VQot57ZEcQFTok hello-from-B-via-DHT
    INFO Sent to 12D3KooWDLGXNskEwn1tFPSSJisnbPh69sTu23VQot57ZEcQFTok: hello-from-B-via-DHT

.. code-block:: console

    # on C
    [12D3KooWLLjeAnSrVfC2CH1SYT1GMGPWvF5eJ2LVmpCAYsswsmN5] hello-from-B-via-DHT

Command reference
-----------------

.. code-block:: console

    $ python -m examples.dht_chat.dht_chat --help

CLI flags:

- ``-p`` / ``--port`` — TCP listen port (``0`` = ephemeral)
- ``-b`` / ``--bootstrap`` — intro peer multiaddr
- ``-n`` / ``--network-size N`` — automated in-process experiment with ``N`` peers

Interactive commands:

- ``id`` — print local Peer ID
- ``addrs`` — print listen multiaddrs
- ``peers`` — connected peers and routing-table size
- ``lookup <peer_id>`` — ``KadDHT.find_peer`` only (no dial)
- ``connect <peer_id>`` — lookup (if needed) then dial
- ``msg <peer_id> <text>`` — send a chat line
- ``help`` / ``quit``

Automated network-size mode
---------------------------

For scaling checks, spin up ``N`` loopback peers in one process. Peer 0 is the
intro node; peers ``1..N-1`` join it; peer 1 looks up peer ``N-1`` by Peer ID
and sends a chat message::

    $ python -m examples.dht_chat.dht_chat --network-size 10
    === DHT network-size experiment: N=10 ===
    Joined 9 peers to intro in 0.25s (intro connected=9)
    Routing table sizes: intro=9 source(peer1)=1 target(peer9)=1 min=1 max=9 median=1
    Peer 1 looked up peer 9 via DHT in 0.29s (1 attempt(s), 1 addr(s))
    Chat delivery OK in 0.00s
    TOTAL N=10: join=0.25s lookup=0.29s msg=0.00s wall=0.56s

On the same machine, ``N=100`` completed successfully as well (join ~1s,
lookup ~0.3s, chat OK). Joiners typically keep a small routing table (often
just the intro) while the intro accumulates everyone; ``find_peer`` still
succeeds because peer 1 queries the intro, which knows the target.

Notes
-----

- All demo peers run KadDHT in **SERVER** mode so they answer FIND_NODE.
- On a small local cluster, DHT query traffic may already dial other joiners
  before you type ``connect``. Use ``lookup`` to always exercise
  ``find_peer`` explicitly.
- This example does not cover NAT traversal or public IPFS bootstrap lists;
  see :doc:`examples.nat`, :doc:`examples.circuit_relay`, and
  :doc:`examples.kademlia` for related topics.
