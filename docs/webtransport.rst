WebTransport
============

py-libp2p ships an experimental **libp2p-webtransport** transport: HTTP/3
WebTransport (ALPN ``h3``) with Noise XX on the first client-opened stream and
dual self-signed certificate rotation (``/certhash/`` in listen multiaddrs).

Spec: https://github.com/libp2p/specs/blob/master/webtransport/README.md

Status: prototype (🌱). Prefer for DPI / censorship experiments and go/js/Kubo
parity; native ``quic-v1`` remains the default high-performance UDP transport.

Enable
------

Pass ``enable_webtransport=True`` to ``new_host`` / ``new_swarm``. Listen on a
WebTransport multiaddr (note ``quic-v1`` then ``webtransport``)::

    from multiaddr import Multiaddr
    from libp2p import new_host

    host = new_host(enable_webtransport=True, enable_tcp=False)
    listen = Multiaddr("/ip4/0.0.0.0/udp/0/quic-v1/webtransport")

Advertised addresses include one or two ``/certhash/<multibase-sha256>``
components plus ``/p2p/<peer-id>``. Dialers **must** use those certhashes;
a wrong hash fails Noise extension verification.

Well-known path
---------------

After the QUIC/TLS handshake (ALPN ``h3``), the client opens an HTTP/3
``CONNECT`` with ``:protocol = webtransport`` to::

    /.well-known/libp2p-webtransport?type=noise

That session carries libp2p streams. The first **client-opened** bidirectional
WebTransport stream runs Noise XX; the server includes the
``webtransport_certhashes`` extension so the dialer can bind Peer ID to the TLS
certificate fingerprints advertised in the multiaddr.

ALPN comparison (censorship story)
----------------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Transport
     - QUIC ALPN
     - On-wire look
   * - Native ``quic-v1``
     - ``libp2p``
     - Distinct from web traffic; easy to DPI
   * - WebTransport
     - ``h3``
     - Ordinary HTTP/3 (same class as modern browsing); CONNECT to a well-known path

**Residual DPI risks:** path fingerprinting on
``/.well-known/libp2p-webtransport``, unusual cert properties, traffic timing,
and blocking all HTTP/3 still apply. WebTransport is camouflage, not a VPN or
MASQUE proxy fleet. For go-libp2p ≥0.49 interop, the server also advertises
draft-15 ``SETTINGS_WT_ENABLED`` (``0x2c7cf000``) alongside aioquic's draft-06
codepoint, and accepts ``:protocol`` values ``webtransport`` and
``webtransport-h3``.


TLS + Noise
-----------

WebTransport **requires** TLS (HTTP/3) **and** Noise for Peer ID authentication.
That is intentional double encryption: TLS authenticates the certificate /
certhash path; Noise authenticates the libp2p identity. Do not drop Noise.

Demo
----

See ``examples/webtransport/webtransport_echo.py`` and
``examples/webtransport/DEMO.md``.

go-libp2p interop
-----------------

Local harness under ``tests/interop/go_libp2p/webtransport/`` (pinned go-libp2p
v0.49.0). Build with ``tests/interop/go_libp2p/scripts/setup_go_webtransport.sh``
and run ``pytest tests/interop/go_libp2p/test_webtransport_interop.py``.
