Multi-Transport
===============

.. contents:: On this page
   :local:
   :depth: 2

Overview
--------

py-libp2p now supports **simultaneous multi-transport listening**, mirroring
`go-libp2p's architecture <https://github.com/libp2p/go-libp2p>`_.  A single
host can accept inbound connections over TCP, WebSocket, and QUIC at the same
time, and will automatically select the correct transport when dialing a peer
based on the protocols in the destination multiaddress.

The implementation centres on three new components:

* :class:`~libp2p.transport.manager.TransportManager` — a routing table that
  maps multiaddresses to transports using a two-step pre-filter (protocol-name
  set intersection followed by :meth:`can_dial` / :meth:`can_listen` checks).
* Extended :class:`~libp2p.abc.ITransport` interface — every transport now
  exposes ``can_dial(maddr)``, ``can_listen(maddr)``, and ``protocols()``
  methods so the manager can route without inspecting class names.
* Updated :class:`~libp2p.network.swarm.Swarm` — accepts a
  ``transports: list[ITransport]`` argument; the deprecated single-transport
  ``transport=`` keyword argument continues to work but emits a
  :class:`DeprecationWarning`.

Quick Start
-----------

**Server** — listen on all three transports at once:

.. code-block:: python

    import multiaddr
    import trio
    from libp2p import new_host
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.custom_types import TProtocol

    ECHO_PROTO = TProtocol("/echo/1.0.0")

    async def echo_handler(stream):
        data = await stream.read()
        await stream.write(data)
        await stream.close()

    async def main():
        listen_addrs = [
            multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/4001"),       # TCP
            multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/4002/ws"),     # WebSocket
            multiaddr.Multiaddr("/ip4/0.0.0.0/udp/4003/quic"),   # QUIC
        ]

        # Pass listen_addrs to new_host so the Swarm's TransportManager
        # is populated with TCP + WebSocket + QUIC at construction time.
        host = new_host(key_pair=create_new_key_pair(), listen_addrs=listen_addrs)
        host.set_stream_handler(ECHO_PROTO, echo_handler)

        async with host.run(listen_addrs=listen_addrs):
            for addr in host.get_addrs():
                print(addr)
            await trio.sleep_forever()

    trio.run(main)

**Client** — detect the required transport from the destination multiaddr and enable it:

.. code-block:: python

    import multiaddr, trio
    from libp2p import new_host
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.custom_types import TProtocol

    ECHO_PROTO = TProtocol("/echo/1.0.0")

    async def main(destination: str):
        maddr = multiaddr.Multiaddr(destination)
        info = info_from_p2p_addr(maddr)

        # Enable the right transport based on the destination address.
        # new_host() must know which transports to register at construction time.
        enable_quic = "/quic" in destination
        enable_websocket = "/ws" in destination

        host = new_host(
            key_pair=create_new_key_pair(),
            enable_quic=enable_quic,
            enable_websocket=enable_websocket,
        )

        async with host.run(listen_addrs=[]):   # client needs no listener
            await host.connect(info)
            stream = await host.new_stream(info.peer_id, [ECHO_PROTO])
            await stream.write(b"hello!")
            print(await stream.read())
            await stream.close()

    # Works for all three transports — just change the address:
    trio.run(main, "/ip4/127.0.0.1/tcp/4001/p2p/<PEER_ID>")          # TCP
    # trio.run(main, "/ip4/127.0.0.1/tcp/4002/ws/p2p/<PEER_ID>")     # WebSocket
    # trio.run(main, "/ip4/127.0.0.1/udp/4003/quic/p2p/<PEER_ID>")   # QUIC

Running the Example
-------------------

The ``examples/multi_transport/`` directory contains ready-to-run scripts.

.. code-block:: console

    # Terminal 1 — start the server
    $ python examples/multi_transport/server.py
    === Multi-Transport Echo Server ===

    Listening on:
      /ip4/0.0.0.0/tcp/4001/p2p/16Uiu2HAm...
      /ip4/0.0.0.0/tcp/4002/ws/p2p/16Uiu2HAm...
      /ip4/0.0.0.0/udp/4003/quic/p2p/16Uiu2HAm...

    Connect using any of the following:

      TCP:       python client.py -d /ip4/127.0.0.1/tcp/4001/p2p/16Uiu2HAm...
      WebSocket: python client.py -d /ip4/127.0.0.1/tcp/4002/ws/p2p/16Uiu2HAm...
      QUIC:      python client.py -d /ip4/127.0.0.1/udp/4003/quic/p2p/16Uiu2HAm...

    # Terminal 2 — connect over TCP
    $ python examples/multi_transport/client.py -d /ip4/127.0.0.1/tcp/4001/p2p/16Uiu2HAm...
    === Multi-Transport Echo Client (TCP) ===
    Connected  ✓  (transport: TCP)
    ✅  Echo verified — round-trip successful!

    # Terminal 2 — connect over WebSocket
    $ python examples/multi_transport/client.py -d /ip4/127.0.0.1/tcp/4002/ws/p2p/16Uiu2HAm...
    === Multi-Transport Echo Client (WebSocket) ===
    Connected  ✓  (transport: WebSocket)
    ✅  Echo verified — round-trip successful!

    # Terminal 2 — connect over QUIC
    $ python examples/multi_transport/client.py -d /ip4/127.0.0.1/udp/4003/quic/p2p/16Uiu2HAm...
    === Multi-Transport Echo Client (QUIC) ===
    Connected  ✓  (transport: QUIC)
    ✅  Echo verified — round-trip successful!

API Reference
-------------

``new_host`` / ``new_swarm`` factory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The factory functions accept several ways to specify transports, in priority
order:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Argument
     - Behaviour
   * - ``transports=[...]``
     - Use exactly the supplied list of :class:`~libp2p.abc.ITransport`
       instances; all other transport arguments are ignored.
   * - ``listen_addrs=[...]``
     - Auto-detect required transports by inspecting each address's protocol
       components (``/tcp``, ``/ws``, ``/quic``, etc.) via the transport
       registry.
   * - ``enable_quic=True``
     - Add a QUIC transport when no QUIC address appears in ``listen_addrs``.
   * - ``enable_websocket=True``
     - Add a WebSocket transport when no WS address appears in ``listen_addrs``.
   * - *(default)*
     - TCP only.

.. code-block:: python

    from libp2p import new_swarm
    from libp2p.transport.tcp.tcp import TCP
    from libp2p.transport.websocket.transport import WebsocketTransport
    from libp2p.transport.quic.transport import QUICTransport

    # Explicit list — full control
    swarm = new_swarm(transports=[TCP(), WebsocketTransport(...), QUICTransport(...)])

    # Auto-detect from addresses
    swarm = new_swarm(listen_addrs=[
        Multiaddr("/ip4/0.0.0.0/tcp/4001"),
        Multiaddr("/ip4/0.0.0.0/tcp/4002/ws"),
        Multiaddr("/ip4/0.0.0.0/udp/4003/quic"),
    ])

``TransportManager``
~~~~~~~~~~~~~~~~~~~~

The :class:`~libp2p.transport.manager.TransportManager` is available via
``swarm.transport_manager`` and exposes the following public methods:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Method
     - Description
   * - ``add_transport(t)``
     - Register a single transport.
   * - ``add_transports([t1, t2, ...])``
     - Register multiple transports at once.
   * - ``for_dialing(maddr)``
     - Return the first transport that can dial *maddr*, or ``None``.
   * - ``for_listening(maddr)``
     - Return the first transport that can listen on *maddr*, or ``None``.
   * - ``get_transports()``
     - Return a copy of the registered transport list.
   * - ``has_transport_for(maddr)``
     - Quick boolean check — shorthand for ``for_dialing(maddr) is not None``.
   * - ``set_background_nursery(nursery)``
     - Propagate the Swarm nursery to all transports that need it (QUIC,
       WebSocket).
   * - ``set_swarm(swarm)``
     - Propagate the Swarm back-reference to all transports that need it.

ITransport interface
~~~~~~~~~~~~~~~~~~~~~

All transport implementations now expose three additional methods:

.. code-block:: python

    class ITransport:
        def can_dial(self, maddr: Multiaddr) -> bool:
            """Return True if this transport can dial the given multiaddress."""

        def can_listen(self, maddr: Multiaddr) -> bool:
            """Return True if this transport can listen on the given multiaddress."""

        def protocols(self) -> list[str]:
            """Return the multiaddr protocol names this transport handles."""

These are used internally by the ``TransportManager`` for fast O(n) routing
with a protocol-name pre-filter; custom transport implementations should
override them.

Migration Guide
---------------

Existing code using a single transport continues to work unchanged:

.. code-block:: python

    # Old API (still works, emits DeprecationWarning)
    from libp2p.transport.tcp.tcp import TCP
    swarm = Swarm(peer_id, peerstore, upgrader, transport=TCP())

    # New API (recommended)
    swarm = Swarm(peer_id, peerstore, upgrader, transports=[TCP()])

The deprecated ``swarm.transport`` property is retained for backward
compatibility and returns the first registered transport; prefer
``swarm.transport_manager`` for new code.

Example Source
--------------

.. literalinclude:: ../examples/multi_transport/server.py
   :language: python
   :caption: examples/multi_transport/server.py
   :linenos:

.. literalinclude:: ../examples/multi_transport/client.py
   :language: python
   :caption: examples/multi_transport/client.py
   :linenos:
