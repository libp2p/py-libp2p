Release Notes
=============

.. towncrier release notes start

py-libp2p v0.8.0 (2026-09-26)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- Moved the ``connection_config`` parameter in ``libp2p.new_host()`` to the end of the function signature.
  This is a breaking API change for callers that pass arguments positionally; use keyword arguments for ``connection_config``. (`#553 <https://github.com/libp2p/py-libp2p/issues/553>`__)
- Removed the ``nursery`` parameter from ``IListener.listen()`` and all concrete listener implementations (TCP, WebSocket, QUIC, Circuit Relay v2). Listeners now own their background task lifetime internally and are cancelled via ``close()``. Callers should update ``await listener.listen(maddr, nursery)`` to ``await listener.listen(maddr)``. (`#1314 <https://github.com/libp2p/py-libp2p/issues/1314>`__)
- Removed the ``libp2p.transport.transport_registry`` module and the legacy ``transport=`` keyword argument from ``Swarm.__init__``. Third-party transports should now be registered using ``TransportManager`` or by passing ``transports=[...]`` to ``Swarm()``. (`#1359 <https://github.com/libp2p/py-libp2p/issues/1359>`__)


Bugfixes
~~~~~~~~

- Bootstrap discovery fixes and go-libp2p spec compliance: DNS-resolved addresses now properly have /p2p/ decapsulated (with ValueError fallback), connection timeout uses trio.fail_after with TooSlowError handling, allow_ipv6 enforced in address filtering, ID.from_string used for peer ID parsing, connection_timeout is configurable (float type), _is_supported_addr is now a @staticmethod, stop() properly clears state for clean restart, exception handling uses specific exception types, periodic reconnection loop added (go-libp2p spec), and unreachable bootstrap peers are removed after 3 consecutive failures (go-libp2p spec). (`#bootstrap_fixes <https://github.com/libp2p/py-libp2p/issues/bootstrap_fixes>`__)
- ``BasicHost.close()`` now stops background services (mDNS, UPnP, bootstrap) and
  cancels identify tasks before closing the network. Test ``HostFactory`` tears
  hosts down via ``close()``, eliminating pending-task warnings (issue #92). (`#92 <https://github.com/libp2p/py-libp2p/issues/92>`__)
- Replaced return True/False pattern with try/catch pattern for better error handling.

  - Updated set_stream_handler method in BasicHost to validate inputs and raise HostException
  - Enhanced mplex stream deadline methods to raise ValueError for invalid TTL instead of returning False
  - Updated TCP listener to raise OpenConnectionError instead of returning False on failure
  - Fixed misleading docstrings in yamux, QUIC stream, swarm, and mplex (`#194 <https://github.com/libp2p/py-libp2p/issues/194>`__)
- Fixed silent swallowing of ``ConnectionResetError`` in TCP connections. When a remote peer resets the connection, ``TrioTCPStream`` now raises ``ConnectionClosedError`` (for ``trio.BrokenResourceError``) instead of silently returning empty bytes. Locally-initiated closures (``trio.ClosedResourceError``) remain silently handled for backward compatibility. (`#376 <https://github.com/libp2p/py-libp2p/issues/376>`__)
- TCP dial now raises ``OpenConnectionError`` instead of leaking
  ``ProtocolLookupError`` when a multiaddr has no TCP component, matching
  listen() and closing the defence-in-depth gap left after #1357 / #391. (`#391 <https://github.com/libp2p/py-libp2p/issues/391>`__)
- Completed Circuit Relay v2 reservation proof wiring by returning signed reservation voucher/signature payloads from HOP RESERVE responses and attaching valid reservation proofs on subsequent HOP CONNECT requests. Also made relay DHT discovery toggle configurable through RelayConfig. (`#691 <https://github.com/libp2p/py-libp2p/issues/691>`__)
- Fixed message ID (mid) handling in pubsub/mcache to use ``bytes`` (``from_id + seqno``) instead of ``tuple[bytes, bytes]``, consistent with go-libp2p's ``DefaultMsgIdFn``. (`#861 <https://github.com/libp2p/py-libp2p/issues/861>`__)
- Fixed GossipSub publish-before-identify timing issue by queueing messages for peers whose protocol negotiation is still in progress, ensuring deterministic message delivery even in rapid connect-and-publish scenarios. (`#887 <https://github.com/libp2p/py-libp2p/issues/887>`__)
- Fixed mplex so a remote stream reset does not discard data that was already buffered. This matches Yamux and allows reading a ping payload that arrives with a concurrent reset. (`#1108 <https://github.com/libp2p/py-libp2p/issues/1108>`__)
- Fixed DHT regression on v0.5.0 where streams failed to open to bootstrap peers due to a race condition in stream muxer initialization. (`#1128 <https://github.com/libp2p/py-libp2p/issues/1128>`__)
- Noise handshake payloads now require X25519 static keys and raise a clear
  error when given an invalid key type. (`#1182 <https://github.com/libp2p/py-libp2p/issues/1182>`__)
- Re-enable the ``test_ipv6_tcp_listen_and_dial`` integration test. The skip was
  added when ``listen()`` took an external nursery; PR #1308 switched to an
  internal system task, making IPv6 listen/dial work correctly. The test now
  passes without modification. (`#1189 <https://github.com/libp2p/py-libp2p/issues/1189>`__)
- Fixed PytestUnknownMarkWarning for the ``integration`` mark and RuntimeWarning from an unawaited coroutine in stream muxer tests, so CI runs without these warnings. (`#1228 <https://github.com/libp2p/py-libp2p/issues/1228>`__)
- Fixed ``BasicHost.get_addrs()`` not announcing externally observed NAT addresses, which previously caused peers behind NAT (e.g. AWS/EC2) to advertise only private/loopback addresses. Added ``ObservedAddrManager`` that collects observed addresses reported by peers via the Identify protocol and advertises them once enough distinct observer groups confirm the same address. (`#1250 <https://github.com/libp2p/py-libp2p/issues/1250>`__)
- Fixed yamux interoperability with go-yamux: SYN/ACK/FIN/RST frames are now sent as TYPE_WINDOW_UPDATE (not TYPE_DATA), writes are serialized with a lock to prevent frame interleaving, and SYN/ACK window values match go-yamux conventions so peers no longer get an inflated send window. (`#1271 <https://github.com/libp2p/py-libp2p/issues/1271>`__)
- Circuit Relay v2 clients open a new HOP stream for CONNECT after RESERVE so relays that finish the substream after one exchange (for example rust-libp2p) work for hole-punch and interop. (`#1304 <https://github.com/libp2p/py-libp2p/issues/1304>`__)
- Fixed yamux handling of WINDOW_UPDATE frames with SYN so the length field is treated as a window increment rather than payload size, improving interop with other libp2p implementations. Also handle FIN and RST flags on SYN stream-open frames. (`#1312 <https://github.com/libp2p/py-libp2p/issues/1312>`__)
- Fixed Kademlia DHT provider advertisement so a failure to open the ADD_PROVIDER stream no longer raises a secondary ``UnboundLocalError``; the underlying connection error is logged instead. (`#1335 <https://github.com/libp2p/py-libp2p/issues/1335>`__)
- Fixed peer record validation to ensure signed ``PeerRecord`` instances have matching signer identity and peer ID, preventing certified address book poisoning for arbitrary peer IDs. (`#1338 <https://github.com/libp2p/py-libp2p/issues/1338>`__)
- Fixed TLS inbound authentication bypass where a remote peer could complete the libp2p TLS handshake without presenting a client certificate and still receive a valid ``SecureSession`` with a synthetic placeholder Peer ID. The server-side SSL context now requests a client certificate, and a missing certificate is treated as a hard handshake failure rather than a recoverable warning. (`#1340 <https://github.com/libp2p/py-libp2p/issues/1340>`__)
- Fixed Circuit Relay v2 issue where a source peer could connect to a destination peer without an active reservation on the relay. (`#1342 <https://github.com/libp2p/py-libp2p/issues/1342>`__)
- Fixed Python perf interop teardown for tls+mplex and listener lifecycle so slow ws+yamux benchmarks complete without false failures during shutdown. (`#1344 <https://github.com/libp2p/py-libp2p/issues/1344>`__)
- Fixed an authentication bypass where inbound QUIC connections were accepted without verifying the peer's libp2p certificate. (`#1345 <https://github.com/libp2p/py-libp2p/issues/1345>`__)
- Fixed a denial-of-service vulnerability where remote pubsub peers could exhaust memory by flooding unique topic subscriptions. (`#1349 <https://github.com/libp2p/py-libp2p/issues/1349>`__)
- Hardened the WebRTC Direct ``POST /sdp`` dev-harness HTTP server against memory-amplification DoS: bounded ``Content-Length`` to 32 KiB (returns 413 on excess), rejected negative/non-integer values with 400, and capped header parsing at 64 lines / 8 KiB to prevent indefinite task hold via slow header flooding. (`#1354 <https://github.com/libp2p/py-libp2p/issues/1354>`__)
- Fixed python×python TLS interop failures with ``TLSV1_ALERT_UNKNOWN_CA`` when using self-signed libp2p identity certificates. The TLS transport now requests peer certificates during the handshake while skipping PKIX CA verification at the OpenSSL layer, deferring identity checks to libp2p extension verification per the libp2p TLS specification. (`#1367 <https://github.com/libp2p/py-libp2p/issues/1367>`__)
- Fixed transport interop listener crashes when publishing IPv6-only multiaddrs. ``_get_ip_value`` now catches ``ProtocolLookupError`` instead of assuming ``value_for_protocol("ip4")`` returns falsy on IPv6 addresses. (`#1371 <https://github.com/libp2p/py-libp2p/issues/1371>`__)
- Fixed identify protocol reporting empty listen addresses under heavy parallel load. Integration tests that depend on identify and peerstore address propagation are now run serially in ``make test`` to avoid xdist timing flakes. (`#1377 <https://github.com/libp2p/py-libp2p/issues/1377>`__)
- quic: remove shared ``QuicLogger`` instance that caused ``QuicLoggerTrace does not belong to QuicLogger`` crashes when multiple concurrent inbound QUIC connections were active. Each connection now uses ``quic_logger=None``, preventing cross-connection trace ownership errors. (`#1390 <https://github.com/libp2p/py-libp2p/issues/1390>`__)
- gossipsub: replay recent messages to a peer once its outbound pubsub stream is registered. When a peer's subscription was processed before that stream existed, the mcache catch-up in ``handle_subscription`` had nothing to write to, so a message published right after connecting was dropped for good. (`#1398 <https://github.com/libp2p/py-libp2p/issues/1398>`__)
- Clean up ``peer_topics`` for pubsub peers that disconnect before their outbound
  stream is registered, and replay the gossipsub message cache at most once per
  peer subscription so a reconnecting peer is no longer handed the whole window
  again. (`#1403 <https://github.com/libp2p/py-libp2p/issues/1403>`__)
- kad-dht: never dial ourselves during a ``FIND_NODE`` lookup, and drop our own peer ID from a response's ``closerPeers`` instead of queueing it as a candidate. A responder may legitimately return the requester -- it is the closest key to itself -- and querying ourselves stalled the lookup until timeout. (`#1405 <https://github.com/libp2p/py-libp2p/issues/1405>`__)
- kademlia-dht: fix random walk stalls caused by artificial ``min_refresh_threshold``, correct KBucket splitting and eviction logic, hash target keys before XOR distance computation, align random walk concurrency with go-libp2p (10), support configurable random walk targets, add discovered peers to routing table, and support ``dnsaddr`` resolution. (`#1413 <https://github.com/libp2p/py-libp2p/issues/1413>`__)
- ping: add per-peer inbound stream limits (max 2) to prevent resource exhaustion, cache and reuse outbound streams, reduce response timeout from 60s to 10s, add write timeouts and ``CancelScope`` support, fix RTT calculations to milliseconds, use ``read_exactly`` for short-read safety, use ``stream.reset()`` on payload mismatch, and wrap metrics loop in try/except to prevent global crash. (`#1414 <https://github.com/libp2p/py-libp2p/issues/1414>`__)
- identify: bound varint prefix loops and add timeouts to prevent unbounded reads, scope identify tasks for cleanup on connection drop, fix signed peer record mismatch handling, replace unbounded cache with LRU (maxsize=1000), fix ``id(conn)`` stale observations with weak references, fix semaphore mutable default, remove 5s synchronous poll delay, fix O(n^2) bytes concatenation, replace protocols instead of appending, clear addresses before re-adding, fix ``_is_public_addr`` false-positives, close response streams, validate ``public_key``, fix case-sensitive ``::ffff:`` check, and cancel tasks on host shutdown. (`#1415 <https://github.com/libp2p/py-libp2p/issues/1415>`__)
- bitswap: rewrite to session-based architecture with ``PeerManager`` and ``BlockPresenceManager``, implement ``WANT_CANCEL`` propagation to save bandwidth, fix memory leaks in pending requests and presence caches with TTL-based cleanup, resolve race conditions with ``set[trio.Event]`` per CID, add ``trio.CancelScope`` for clean shutdown, enforce block size limits (512KB) and CID validation, and add comprehensive error handling for network operations. (`#1416 <https://github.com/libp2p/py-libp2p/issues/1416>`__)
- mDNS peer discovery now uses spec-compliant ``dnsaddr`` TXT records, supports IPv4 and IPv6, filters unsuitable addresses (circuit relay, browser transports), and resolves the ``remove_service`` ``KeyError`` crash. (`#1419 <https://github.com/libp2p/py-libp2p/issues/1419>`__)
- yamux: release the per-connection ``stream_backlog_semaphore`` slot when a stream is closed or reset. Slots were previously consumed permanently, so any connection that opened more than 256 streams over its lifetime — e.g. the bitswap client opening one wantlist stream per batch while transferring a large (multi-GB) file — would block forever in ``open_stream`` and hang the transfer. Bitswap response readers are now also scoped to the CIDs their own wantlist covered: they close their stream once that batch is complete instead of lingering until the whole transfer finishes, and no longer report other streams' pending blocks as missing. (`#1420 <https://github.com/libp2p/py-libp2p/issues/1420>`__)
- Fix resource leaks that accumulate on long-running nodes: yamux now sweeps
  fully-closed streams whose receive buffers still hold unread data (previously
  they leaked one entry per stream for the connection's lifetime), and the
  bitswap client now reaps all per-peer state (wantlists, negotiated protocols,
  pending bytes, peer stats, presence) when a peer's last connection closes, via
  a new INotifee integration. (`#1421 <https://github.com/libp2p/py-libp2p/issues/1421>`__)
- Kademlia DHT ``FIND_NODE`` queries to a single peer are bounded by ``QUERY_TIMEOUT``, so a peer that opens the query stream but never replies cannot stall ``find_peer``, ``provide``, ``find_providers`` or routing-table refresh; a regression test now covers the silent-peer case. (`#1434 <https://github.com/libp2p/py-libp2p/issues/1434>`__)
- Enforce go-mplex MaxMessageSize (1 MiB) on mplex frame reads, chunk large writes, and apply receive-timeout backpressure so oversized frames cannot exhaust memory. (`#1436 <https://github.com/libp2p/py-libp2p/issues/1436>`__)
- Fixed the WebRTC-Direct inbound path, which never completed: the listener now runs the
  Noise XX handshake (as initiator, per spec) on the trio side and hands the authenticated
  ``WebRTCConnection`` to the handler; the dialer is the Noise responder and verifies the
  ``/p2p/`` peer ID after the handshake. Also fixed ``get_remote_fingerprint`` (read non-
  existent aiortc attributes, so ``dial()`` always failed),
  ``DataChannelReadWriter.read(n)`` now honours ``n`` (the Noise packet reader needs the
  2-byte length prefix alone), the Noise prologue is role-ordered (dialer fingerprint,
  then server), and the noise channel ``send`` waits for the channel to open, and the
  handshake bytes are framed as ``webrtc.pb.Message`` stream frames on channel 0 like
  go/js (was raw). The dialer bounds the Noise phase with ``handshake_timeout`` and closes
  the peer connection on every failure path; a raising connection handler no longer takes
  down the listeners trio run. ``PatternXX.handshake_outbound`` accepts
  ``remote_peer=None`` for initiators that learn the peer ID from the handshake. Data-
  channel framing is now decoded as a byte stream (frames may be split or batched across
  SCTP messages, as go-libp2p sends the varint prefix and body separately), for both the
  Noise channel and streams; previously every py<->go WebRTC-Direct connection failed with
  ``malformed handshake frame length``. Opening a data channel re-seeds aiortc's stream-id
  allocator parity from the DTLS role (client even, server odd, RFC 8832) instead of its
  ICE-role default, which collided with go-libp2p's even dialer IDs on a py listener. (`#1437 <https://github.com/libp2p/py-libp2p/issues/1437>`__)
- Kademlia DHT and Rendezvous now reject varint-prefixed messages larger than 4 MiB to prevent remote memory exhaustion. (`#1438 <https://github.com/libp2p/py-libp2p/issues/1438>`__)
- Harden the varint decoders in ``libp2p.utils.varint`` against malformed input. ``decode_uvarint`` now raises ``ParseError`` on a truncated varint (one whose final byte still has the continuation bit set) instead of silently returning a partial value, and ``decode_uvarint_from_stream`` rejects an over-long (11-byte) varint that would encode a value larger than 64 bits. (`#1440 <https://github.com/libp2p/py-libp2p/issues/1440>`__)
- GossipSub now GRAFTs peers into an underfilled mesh when their subscription is
  observed, so publish after join/connect no longer waits on the next heartbeat. (`#1454 <https://github.com/libp2p/py-libp2p/issues/1454>`__)
- Reject 10-byte uvarint encodings whose terminating byte overflows 64 bits, and align ``decode_uvarint`` over-long failures to ``ParseError``. (`#1458 <https://github.com/libp2p/py-libp2p/issues/1458>`__)
- GossipSub ``ControlIHave`` / ``ControlIWant`` ``messageIDs`` are now opaque
  bytes (matching the GossipSub RPC schema and ``ControlIDontWant``), so binary
  message IDs no longer raise ``UnicodeDecodeError`` on the control path. (`#1463 <https://github.com/libp2p/py-libp2p/issues/1463>`__)
- Fixed persistent peerstore restore so public and private keys survive process restarts when using durable backends such as SQLite. (`#1466 <https://github.com/libp2p/py-libp2p/issues/1466>`__)
- ``RawConnection.read()`` and ``RawConnection.write()`` now catch
  ``ConnectionResetError`` from the underlying stream and wrap it in
  ``RawConnError``, preventing OS-level connection-reset errors from leaking to
  callers that expect ``RawConnError`` for all connection failures. (`#1468 <https://github.com/libp2p/py-libp2p/issues/1468>`__)
- The WebRTC-Direct listener now sets the dialer's ICE credentials on the muxed connection before replaying the first-contact STUN packet. A full-ICE dialer (e.g. go-libp2p) that checks from multiple host candidates no longer strands the peer-reflexive pair it later nominates, so inbound ``go -> py`` dials complete instead of stalling after ICE; the go-libp2p interop suite now exercises both directions for real. (`#1470 <https://github.com/libp2p/py-libp2p/issues/1470>`__)
- AnyIOManager cancellation now waits on an ``anyio.Event`` instead of busy-polling,
  matching TrioManager so service shutdown is prompt under load (fixes Windows CI flake). (`#1472 <https://github.com/libp2p/py-libp2p/issues/1472>`__)
- Close a swarm's live connections when it shuts down so their sockets are released
  instead of leaking, and treat ``ResourceWarning`` as an error in pytest so future
  socket leaks fail CI. ``Swarm.run()``'s service-manager shutdown closes tracked
  connections and transports (not just listeners); test fixtures tear hosts/swarms
  down while services are still running. Completes the work deferred from #1486
  (issues #92, #1485). (`#1485 <https://github.com/libp2p/py-libp2p/issues/1485>`__)
- ``Mplex.close()`` now closes the underlying secured connection even when the muxer is already shutting down. Previously it returned early once ``event_shutting_down`` was set, and the read loop's ``_cleanup()`` sets that flag on a peer-initiated EOF without closing the socket — so whenever the remote closed first, the local socket leaked (``ResourceWarning: unclosed socket``). This mirrors ``Yamux.close()``, which already closed unconditionally, and clears the residual stream-muxer socket leaks tracked in #1487. (`#1487 <https://github.com/libp2p/py-libp2p/issues/1487>`__)
- Clear residual unclosed-socket / event-loop ``ResourceWarning`` leaks across the
  core test suite and enable ``filterwarnings = ["error::ResourceWarning"]`` so
  new socket leaks fail CI. Completes the deferred guard from #1485 / #1486 and
  closes #1498. (`#1498 <https://github.com/libp2p/py-libp2p/issues/1498>`__)
- Fixed WebRTC Direct experimental ``/sdp`` harness listen on Windows by binding
  TCP first for ephemeral ports, then UDP on the same number, so Hyper-V excluded
  port ranges no longer fail ``listen()`` with ``WinError 10013``. (`#1501 <https://github.com/libp2p/py-libp2p/issues/1501>`__)
- Fixed WebTransport self-signed leaf generation so Chromium accepts ``/certhash/`` pins via ``serverCertificateHashes`` (empty subject, BasicConstraints/KeyUsage/EKU aligned with go-libp2p; default validity 13 days). (`#1514 <https://github.com/libp2p/py-libp2p/issues/1514>`__)
- Quietly exit `host.run` / `host.close` when muxer background tasks see expected peer hangup, so apps no longer need ExceptionGroup teardown swallows. (`#1516 <https://github.com/libp2p/py-libp2p/issues/1516>`__)
- QUIC stream writes now apply send-side backpressure so writers wait when the transport send buffer is full, making upload throughput measurements honest. (`#1520 <https://github.com/libp2p/py-libp2p/issues/1520>`__)
- Fixed QUIC stream half-close so peers observe FIN and request/response protocols (including perf download) complete correctly. (`#1521 <https://github.com/libp2p/py-libp2p/issues/1521>`__)
- Fix tls+mplex teardown hang: SecureSession raises ConnectionClosedError on EOF, and Mplex cleans up idempotently if the read loop exits without setting event_closed. (`#1526 <https://github.com/libp2p/py-libp2p/issues/1526>`__)
- Improve honest QUIC throughput: stop forcing a 1ms event-loop sleep after every batch, wire max_datagram_size to UDP MTU (not the DATAGRAM frame size), expose cubic/initial_rtt on QUICTransportConfig, and coalesce transmits per write watermark batch. (`#1528 <https://github.com/libp2p/py-libp2p/issues/1528>`__)
- Ignore late FIN-only events on already-closed inbound QUIC streams so they no longer starve ``accept_stream()`` under concurrent load. (`#1530 <https://github.com/libp2p/py-libp2p/issues/1530>`__)
- Fixed the Rendezvous client advertising ``/p2p``-suffixed addresses in REGISTER messages. Strict servers dial back advertised addresses to verify reachability and rejected these registrations, so registering against non-Python servers failed. The client now advertises bare transport addresses. (`#1535 <https://github.com/libp2p/py-libp2p/issues/1535>`__)
- Fixed Circuit Relay v2 spec compliance so reservations, STOP flows, and length-delimited framing interoperate with go-libp2p and rust-libp2p relays and peers. (`#1537 <https://github.com/libp2p/py-libp2p/issues/1537>`__)
- Replaced the custom AutoNAT wire schema with the spec's proto2 definition and implemented both protocol halves: the server only dials addresses based on the requester's observed IP and refuses relayed requests, and a new client aggregates server verdicts into a reachability status using the specified more-than-three-servers heuristic. (`#1540 <https://github.com/libp2p/py-libp2p/issues/1540>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Installation documentation now recommends ``uv`` as the primary package manager, with ``pip`` documented as an alternative, including development setup for both workflows. (`#1175 <https://github.com/libp2p/py-libp2p/issues/1175>`__)
- Noise transport examples now show a dedicated X25519 static key instead of
  reusing the host identity key for Noise encryption. (`#1182 <https://github.com/libp2p/py-libp2p/issues/1182>`__)
- Updated contributor setup documentation to use ``uv sync`` with the default ``.venv`` workflow, including clearer setup-script guidance for Linux and macOS. (`#1248 <https://github.com/libp2p/py-libp2p/issues/1248>`__)
- Document Filecoin protocol support and gaps with a machine-readable
  support matrix, and expose a gossipsub compatibility snapshot from the
  read-only Filecoin pubsub observer demo. (`#1267 <https://github.com/libp2p/py-libp2p/issues/1267>`__)
- Consolidated the ``libp2p.utils`` package documentation into a single page, removing the duplicate module entry and adding missing ``address_validation`` and ``dns_utils`` submodule docs. (`#1296 <https://github.com/libp2p/py-libp2p/issues/1296>`__)
- Extended the announce-addrs example CLI with ``--factory-extra``
  (``addrs_factory`` compose mode) and ``--disable-identify-address-discovery``,
  and clarified that the flag skips observed-address discovery only (Identify
  itself still runs for peer metadata). (`#1478 <https://github.com/libp2p/py-libp2p/issues/1478>`__)
- Document Filecoin network parity expectations versus Lotus/Forest and add a
  machine-readable interop matrix with reproducible Filecoin demo workflows. (`#1481 <https://github.com/libp2p/py-libp2p/issues/1481>`__)
- Document the two WebRTC-Direct signalling paths (the spec STUN listener vs the dev-only ``POST /sdp`` harness) and add v1-vs-v2 dial guidance — v1 as the migration default and v2 (libp2p/specs#715) as the recommended flow that browser dialling will require — in the ``libp2p.transport.webrtc`` package docstring and the README. (`#1511 <https://github.com/libp2p/py-libp2p/issues/1511>`__)


Features
~~~~~~~~

- py-libp2p now uses trio exclusively for async operations, removing remaining asyncio usage. (`#174 <https://github.com/libp2p/py-libp2p/issues/174>`__)
- Migrated remaining asyncio usage with trio, so the codebase uses a single async runtime. (`#301 <https://github.com/libp2p/py-libp2p/issues/301>`__)
- Add opt-in peer identity persistence: ``save_identity`` / ``load_identity`` /
  ``create_identity_from_seed``, a ``FileSystemKeyStore`` for named keys, and
  ``key_pair_provider`` / ``keystore`` parameters on ``new_host`` / ``new_swarm``
  so nodes can keep a stable Peer ID across restarts without changing the default
  random-identity behavior. (`#312 <https://github.com/libp2p/py-libp2p/issues/312>`__)
- Added explicit ``wait_for_peer()`` and ``wait_for_subscription()`` methods to the pubsub API. These methods allow tests and applications to wait for actual state changes (peer stream establishment and topic subscriptions) instead of using arbitrary ``trio.sleep()`` calls, eliminating race conditions when dealing with new peers and pubsub subscriptions. (`#418 <https://github.com/libp2p/py-libp2p/issues/418>`__)
- Replaced the legacy async_service implementation with a new anyio_service framework built on AnyIO for better maintainability and structured concurrency. Import paths change from ``libp2p.tools.async_service`` to ``libp2p.tools.anyio_service``; the public API (``Service``, ``background_trio_service``) is unchanged. (`#524 <https://github.com/libp2p/py-libp2p/issues/524>`__)
- Added **experimental** WebRTC transport scaffolding (``libp2p.transport.webrtc``)
  per the libp2p WebRTC and WebRTC Direct specs.  Enabled via the optional
  ``libp2p[webrtc]`` extra (``aiortc``) and the ``enable_webrtc`` opt-in.

  This is a v1 **node-to-node** foundation, not a production-ready WebRTC stack.

  **What works (node-to-node):**

  - ``WebRTCDirectTransport`` (``/webrtc-direct``) and ``WebRTCPrivateTransport``
    (``/webrtc`` via Circuit Relay v2).
  - Data-channel stream framing with uvarint length-prefixed protobuf and the
    FIN / FIN_ACK / STOP_SENDING / RESET state machine.
  - In-band data channels for application streams; the Noise channel (id=0)
    remains negotiated per spec.
  - Signaling with bilateral ``ICE_DONE`` (libp2p/specs#585 fix).
  - Noise XX prologue binding the handshake to the DTLS certificate fingerprints.
  - SDP builder with an isolated ``_apply_ice_credentials()`` seam for
    libp2p/specs#672.
  - ECDSA P-256 certificate generation with multihash / multibase fingerprint
    encoding; DTLS cert pinned to ``RTCPeerConnection`` via the aiortc-internal
    private slot so the advertised ``/certhash/`` matches the actual handshake.
  - A clean trio ↔ asyncio bridge for ``aiortc``.

  **Out of scope for this PR (follow-ups):**

  - **Browser interop is explicitly NOT supported.**  v1 SDP munging on the
    browser side is being phased out by Chrome's ``WebRTC-NoSdpMangleUfrag``
    field trial; browser dial will land on v2 (libp2p/specs#715).
  - Interop with go-libp2p / js-libp2p WebRTC Direct dialers.  Their listener
    reconstructs the offer from the inbound STUN ``USERNAME``; our listener
    currently uses an HTTP ``POST /sdp`` exchange, which is documented as a
    py-to-py temporary harness.
  - Private ``/webrtc`` dial — only the listener / signaling skeleton lands here.
  - Full inbound handler wiring (Noise + handler invocation) on the
    ``WebRTCDirectListener`` is pending the aiortc STUN ``USERNAME`` exposure
    spike (sub-issue of #546).

  Refs #546. (`#546 <https://github.com/libp2p/py-libp2p/issues/546>`__)
- Implemented advanced connection management features including priority-based dial queues, automatic reconnection, connection limits and pruning, rate limiting, IP allow/deny lists, DNS resolution, and comprehensive connection metrics.
  These features bring py-libp2p's connection management capabilities in line with JavaScript libp2p. (`#553 <https://github.com/libp2p/py-libp2p/issues/553>`__)
- Added a DHT Peer-ID chat example that looks up peers via KadDHT after a one-time bootstrap intro. (`#880 <https://github.com/libp2p/py-libp2p/issues/880>`__)
- Add per-peer outbound RPC queue with priority support and message splitting, matching go-libp2p-pubsub's ``rpcQueue`` and ``split`` pipeline. GossipSub and FloodSub now route all sends through bounded queues instead of writing directly to streams. (`#891 <https://github.com/libp2p/py-libp2p/issues/891>`__)
- Added GossipSub protocol versions 1.3 and 1.4 support, including extensions framework, adaptive gossip dissemination, enhanced peer scoring (P5-P7), rate limiting for IWANT/IHAVE/GRAFT, IP colocation tracking, and configurable message ID generators. (`#992 <https://github.com/libp2p/py-libp2p/issues/992>`__)
- Added optional ``strict_validation`` parameter to ``KadDHT``. When enabled, all DHT record keys must use a registered namespace validator; non-namespaced or unknown-namespace keys are rejected. Default remains permissive for backward compatibility, aligning with go-libp2p and rust-libp2p behavior. (`#1070 <https://github.com/libp2p/py-libp2p/issues/1070>`__)
- Added standardized methods to connection interfaces to access transport address information and connection type without requiring low-level connection access. Connections now expose ``get_transport_addresses()`` and ``get_connection_type()`` methods to determine if a connection is direct or relayed, and to retrieve the actual transport addresses used. (`#1093 <https://github.com/libp2p/py-libp2p/issues/1093>`__)
- Add optional connection health monitoring and load-balancing strategies.

  This is a Python-local, opt-in QoS extension inspired by go-libp2p ConnMgr
  (Protect/tags), peerstore LatencyEWMA, and swarm best-connection selection.
  go-libp2p does not provide a proactive health monitor or auto-replace of
  unhealthy connections; those behaviors are disabled by default here.

  When enabled, hosts can track per-connection health metrics, run periodic
  checks, select connections with ``best`` / ``health_based`` / ``latency_based``
  strategies, and replace unhealthy connections only after a successful
  replacement dial (skipping ConnMgr-protected peers). (`#1121 <https://github.com/libp2p/py-libp2p/issues/1121>`__)
- Added ``IPNSValidator`` for the Kademlia DHT, enabling validation of IPNS records
  per the `IPNS Record Specification <https://specs.ipfs.tech/ipns/ipns-record/>`_
  (V2 signatureV2, DAG-CBOR data, expiry, V1/V2 consistency). The ``/ipns``
  namespace is now validated by default alongside the ``/pk`` namespace. (`#1157 <https://github.com/libp2p/py-libp2p/issues/1157>`__)
- Added implementation of the libp2p perf protocol for measuring transfer performance.

  The perf protocol allows benchmarking data transfer speeds between libp2p nodes. It includes:
  - ``PerfService`` class for perf protocol server/client operations
  - ``measure_performance()`` method to measure upload/download throughput to a remote peer
  - Server-side handling for responding to perf protocol requests
  - Detailed metrics output including latency, upload/download times, and throughput in bytes/second

  See the spec at https://github.com/libp2p/specs/blob/master/perf/perf.md (`#1169 <https://github.com/libp2p/py-libp2p/issues/1169>`__)
- Enhanced DNS support in bootstrap discovery.

  - Bootstrap now treats ``dns``, ``dns4``, ``dns6``, and ``dnsaddr`` as DNS addresses (previously only ``dnsaddr`` was recognized), enabling IPv4/IPv6-specific bootstrap entries.
  - DNS resolution is wrapped in exception handling; failed or empty resolutions are logged and bootstrap continues with the next address.
  - User-facing documentation and examples for DNS bootstrap addresses were added in the Getting Started guide and the bootstrap discovery API docs. (`#1187 <https://github.com/libp2p/py-libp2p/issues/1187>`__)
- Added AutoTLS support for QUIC transport, including QUIC address handling in the AutoTLS flow and loading cached ACME certificates for QUIC TLS configuration. Also propagated ``enable_autotls`` through normal host/swarm QUIC transport construction so QUIC nodes created via ``new_host`` can use AutoTLS when enabled. (`#1190 <https://github.com/libp2p/py-libp2p/issues/1190>`__)
- Added the metrics module to monitor internal service activities via Prometheus/Grafana dashboards. (`#1199 <https://github.com/libp2p/py-libp2p/issues/1199>`__)
- Added ``IHost.remove_stream_handler()`` and ``IMultiselectMuxer.remove_handler()`` to allow services to cleanly unregister protocol handlers during shutdown. Migrated Circuit Relay v2, DCUtR, Bitswap, and Perf services to use the new API, replacing ad-hoc workarounds. (`#1227 <https://github.com/libp2p/py-libp2p/issues/1227>`__)
- GossipSub v1.3 Extensions and Topic Observation support.

  - Added Extensions Control Message mechanism per GossipSub v1.3 spec; extensions are advertised in the first message on the stream and gated to v1.3+ protocol negotiation.
  - Added Topic Observation extension: peers can observe topics without full subscription via ``start_observing_topic()`` and ``stop_observing_topic()``, receiving IHAVE notifications for presence awareness.
  - Added test extension for cross-implementation interop (go-libp2p, rust-libp2p, py-libp2p). (`#1231 <https://github.com/libp2p/py-libp2p/issues/1231>`__)
- Bitswap CID handling now uses the py-cid library. Existing byte-returning APIs are unchanged; new helpers and object-returning APIs are available for new code. (`#1234 <https://github.com/libp2p/py-libp2p/issues/1234>`__)
- Bitswap now accepts canonical CID text, ``/ipfs/...`` CID paths, hex CID strings, and CID objects across client/store/message/DAG boundaries while preserving byte-based wire and storage compatibility. The Bitswap example CLI now accepts canonical/path/hex CID input forms for ``--cid`` and displays canonical CID text in output. (`#1246 <https://github.com/libp2p/py-libp2p/issues/1246>`__)
- Added ``announce_addrs`` support to ``BasicHost`` so nodes behind NAT or
  reverse proxies can advertise their publicly reachable addresses instead of
  local listen addresses. (`#1250 <https://github.com/libp2p/py-libp2p/issues/1250>`__)
- Bitswap's internal data structures (client wantlists, block store) now fully utilize ``py-cid`` objects (``CIDObject``) instead of raw ``bytes`` as keys. Public APIs continue to accept ``CIDInput`` transparently. The legacy ``cid_to_string`` and ``parse_cid_version`` helpers have been removed in favor of the new ``parse_cid`` and ``cid_to_text`` functions, and the ``__init__.py`` exports have been organized into preferred and backward-compatible tiers. **Breaking change:** external code that imports ``cid_to_string`` or ``parse_cid_version`` must migrate to ``cid_to_text`` and ``parse_cid(cid).version``, respectively. (`#1264 <https://github.com/libp2p/py-libp2p/issues/1264>`__)
- Added yamux receive window auto-tuning: the per-stream receive window starts at 256 KB and doubles each RTT epoch up to 16 MB, matching go-yamux behavior for improved throughput on high-bandwidth connections. (`#1270 <https://github.com/libp2p/py-libp2p/issues/1270>`__)
- Replaced lock-step batch querying in DHT operations with semaphore-based sliding window concurrency, so a new query starts as soon as any in-flight query completes instead of waiting for the whole batch. (`#1273 <https://github.com/libp2p/py-libp2p/issues/1273>`__)
- Align PubSub and GossipSub routing with Go's `go-libp2p-pubsub` by deferring dropped outbound control RPCs (Graft/Prune) and subscription announcements for later retry. (`#1276 <https://github.com/libp2p/py-libp2p/issues/1276>`__)
- Added a new ``libp2p.filecoin`` DX package with pinned Filecoin protocol/topic/bootstrap
  constants, runtime bootstrap helpers, Filecoin pubsub preset builders, a new ``filecoin-dx``
  CLI, and a Filecoin pubsub demo workflow. (`#1279 <https://github.com/libp2p/py-libp2p/issues/1279>`__)
- Added semaphore-based stream concurrency limiting at the Swarm level so ``new_stream`` queues when the limit is reached instead of raising immediately, and stream resources are properly released on close. (`#1285 <https://github.com/libp2p/py-libp2p/issues/1285>`__)
- Added a new ``libp2p.request_response`` helper that provides safe one-shot request/response exchanges with framed messages, bounded payload sizes, default timeouts, pluggable codecs, and a generic demo. (`#1287 <https://github.com/libp2p/py-libp2p/issues/1287>`__)
- Added an ``agentic-request-response-demo`` example that uses
  ``libp2p.request_response`` to model Filecoin-aligned capability discovery and
  storage-style task submission with simulated complete, partial, and rejected
  results. (`#1294 <https://github.com/libp2p/py-libp2p/issues/1294>`__)
- Added a callable ``addrs_factory`` (go-libp2p ``AddrsFactory`` parity) and
  ``disable_identify_address_discovery`` so hosts can compose advertised
  addresses and optionally opt out of Identify-driven observed-address discovery. (`#1311 <https://github.com/libp2p/py-libp2p/issues/1311>`__)
- Implement comprehensive Bitswap interoperability with IPFS Kubo, including raw-leaf chunks, canonical DAG-PB internal-node encoding, and balanced layout support. Introduces ``FilesystemBlockStore`` and ``BlockService`` for robust block caching, Bitswap batch fetching, and streaming inputs (``chunk_stream``). (`#1347 <https://github.com/libp2p/py-libp2p/issues/1347>`__)
- Added ``libp2p.transport.webrtc._udp_mux.UdpMux`` — a shared UDP socket dispatcher for WebRTC-Direct inbound connections. Routes pre-ICE STUN datagrams by ``USERNAME`` ufrag prefix and post-ICE DTLS/SCTP frames by remote address, enabling a single fixed port to demultiplex concurrent inbound dials without spinning up a separate socket per peer (prerequisite for a spec-aligned WebRTC-Direct v2 listener, libp2p/specs#715). (`#1352 <https://github.com/libp2p/py-libp2p/issues/1352>`__)
- Add multi-transport support to ``Swarm``, ``new_swarm``, and ``new_host``.
  A node can now listen and dial over TCP, WebSocket, and QUIC simultaneously,
  matching go-libp2p's ``TransportManager`` architecture.  Pass an explicit
  ``transports=[...]`` list to ``new_swarm`` / ``new_host``, or let transports
  be auto-detected from ``listen_addrs``. (`#1359 <https://github.com/libp2p/py-libp2p/issues/1359>`__)
- Enforce IP subnet diversity in Kademlia k-buckets (issue #1383): a new peer is rejected if its globally-routable ``/24`` (IPv4) or ``/48`` (IPv6) subnet already holds ``MAX_PEERS_PER_SUBNET`` (default 2) peers in that bucket, raising the cost of eclipse attacks that grind peer IDs from a single subnet. Loopback, private, CGNAT, link-local, DNS-named, and relayed (``p2p-circuit``) peers are exempt; set ``MAX_PEERS_PER_SUBNET`` to 0 to disable. (`#1383 <https://github.com/libp2p/py-libp2p/issues/1383>`__)
- kad-dht: ``FIND_NODE`` replies now include the target peer itself when we know its addresses, even when the target is the requester or ourselves, matching go-libp2p. This lets a peer ask the network for its own observed addresses, and keeps client-mode peers reachable through the DHT. (`#1405 <https://github.com/libp2p/py-libp2p/issues/1405>`__)
- Made the per-bucket subnet-diversity limit runtime-configurable via a ``max_peers_per_subnet`` argument on ``RoutingTable``, ``KBucket`` and ``KadDHT`` (issue #1422), and added an opt-in table-wide IP-group cap (``max_peers_per_subnet_table``) limiting peers sharing one subnet across all k-buckets (issue #1421). (`#1422 <https://github.com/libp2p/py-libp2p/issues/1422>`__)
- Added ``RoutingTableDiagnostics`` to ``libp2p.kad_dht``, providing operators with a read-only health-inspection surface for the Kademlia routing table: bucket fill rates, keyspace coverage gaps, peer freshness distribution, and a composite 0-100 health score. (`#1432 <https://github.com/libp2p/py-libp2p/issues/1432>`__)
- Added a spec-aligned WebRTC-Direct listener: one shared UDP port (``UdpMux``), inbound
  dials dispatched by the STUN ``USERNAME`` ufrag with ``libp2p+webrtc+v1/`` version-
  prefix validation (unknown/missing prefixes are rejected, never assumed v1), the
  dialer's offer inferred from its first STUN packet, DTLS fingerprint verification
  disabled for inbound per spec (Noise authenticates), a per-source-IP token bucket on
  first-contact STUN (before any parsing or ICE allocation), and an in-flight cap on
  unauthenticated inbounds. The spec-path dial configures no STUN/TURN servers
  (``ice_servers`` now only applies to the HTTP harness). Our dialer now speaks WebRTC-
  Direct v1 (``libp2p+webrtc+v1/`` ufrag == pwd on both the local offer and a synthesised
  ICE-Lite answer built from the multiaddr), so py↔py loopback exercises the real STUN
  path. The HTTP ``POST /sdp`` signaling harness is now opt-in via
  ``WebRTCTransportConfig(enable_sdp_http_harness=True)`` (experimental, py↔py only). New
  helpers in ``libp2p.transport.webrtc.sdp``: ``parse_direct_username``,
  ``build_inferred_offer``, ``build_synthetic_answer``, ``make_v1_credential``; ICE
  credentials are generated with ice-chars only. The listener now also accepts the WebRTC-
  Direct v2 flow (libp2p/specs#715, ``libp2p+webrtc+v2/<client-pwd>`` server ufrag, no SDP
  munging), and the dialer can opt in with
  ``WebRTCTransportConfig(webrtc_direct_dial_version=2)`` (default stays v1 while the spec
  change is unmerged). (`#1437 <https://github.com/libp2p/py-libp2p/issues/1437>`__)
- The opt-in connection health monitor now probes each connection with ``/ipfs/ping/1.0.0``, with Sphinx docs, a live demo TUI/web UI, and extra config flags for busy-connection skip, peerstore RTT, and abort-on-ping-failure. (`#1453 <https://github.com/libp2p/py-libp2p/issues/1453>`__)
- Filecoin connect, ping/identify, and pubsub demos can report negotiated transport, security, and muxer metadata in their JSON probe output. (`#1482 <https://github.com/libp2p/py-libp2p/issues/1482>`__)
- Added experimental libp2p WebTransport (``/quic-v1/webtransport``) on aioquic:
  HTTP/3 ALPN ``h3``, Noise XX with ``webtransport_certhashes``, dual cert rotation,
  host flag ``enable_webtransport``, go-libp2p interop harness, and echo demo.
  Also maps QUIC ``CONNECTION_FLOW_CONTROL_WINDOW`` / ``STREAM_FLOW_CONTROL_WINDOW``
  onto aioquic ``max_data`` / ``max_stream_data`` for multi-stream stability. (`#1507 <https://github.com/libp2p/py-libp2p/issues/1507>`__)
- Made DCUtR hole punching spec-compliant (RTT synchronization, dial coordination, TCP simultaneous open with ``SO_REUSEPORT``) so direct connectivity can be established with go-libp2p and rust-libp2p peers behind NATs. (`#1537 <https://github.com/libp2p/py-libp2p/issues/1537>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Simplified upgrader by consolidating duplicated multistream-select negotiation logic from SecurityMultistream and MuxerMultistream into a reusable GenericMultistreamSelector class. Fixed attribute naming bug (multistream_client → multiselect_client) in MuxerMultistream. (`#313 <https://github.com/libp2p/py-libp2p/issues/313>`__)
- Add shared pubsub test fixtures (``GossipSubHarness``, ``gossipsub_nodes``, ``connected_gossipsub_nodes``, ``subscribed_mesh``) and reusable polling helpers (``wait_for``, ``wait_for_convergence``) to support the pubsub test suite refactor. (`#378 <https://github.com/libp2p/py-libp2p/issues/378>`__)
- Removed dead code from ``CircuitV2Transport`` left over from the old relay
  selection strategy (``_relay_list``, ``_last_relay_index``, ``_relay_metrics``,
  and ``_measure_relay``), which were superseded by ``RelayPerformanceTracker``
  introduced in https://github.com/libp2p/py-libp2p/pull/972. (`#735 <https://github.com/libp2p/py-libp2p/issues/735>`__)
- Replaced generic ``Any`` type annotations with a specific ``MetadataValue`` type alias (``str | int | float | bool | None``) for peer metadata handling, improving type safety and code clarity. Added runtime type validation in ``PeerData.put_metadata()`` to prevent storage of non-serializable objects. Also fixed ``get_metadata()`` return type from ``IPeerMetadata`` to ``MetadataValue``. (`#911 <https://github.com/libp2p/py-libp2p/issues/911>`__)
- Improved cross-platform path handling and added path audit to pre-commit. (`#944 <https://github.com/libp2p/py-libp2p/issues/944>`__)
- Add type stubs for ``miniupnpc`` to provide proper type information and replace the ``type: ignore`` workaround. (`#1009 <https://github.com/libp2p/py-libp2p/issues/1009>`__)
- Improved Mplex edge-case warning logs and corrected QUIC/Mplex type annotations. (`#1135 <https://github.com/libp2p/py-libp2p/issues/1135>`__)
- Replaced bare ``print()`` calls in test modules with logger-based output so test verbosity is configurable and consistent with project conventions. (`#1207 <https://github.com/libp2p/py-libp2p/issues/1207>`__)
- Replaced fragile string matching on exception messages with typed exception subclasses across QUIC, TLS, WebSocket, Circuit Relay, and Bootstrap modules, and updated tests to assert on structured exception attributes. (`#1218 <https://github.com/libp2p/py-libp2p/issues/1218>`__)
- Replace the last string-constructed ``decapsulate(Multiaddr("/p2p/..."))`` call with the protocol-code API ``decapsulate_code(P_P2P)`` in Identify's ``_strip_p2p_suffix`` (the websocket and circuit-relay sites were already migrated). This is value- and order-independent and a no-op when ``/p2p`` is absent; for a relay/circuit listen address it now strips only the trailing peer id (keeping ``/p2p/<relay>/p2p-circuit``) instead of truncating at the first ``/p2p``. (`#1223 <https://github.com/libp2p/py-libp2p/issues/1223>`__)
- Improved OSO observability report reliability by correctly detecting rcmgr metric availability, continuing vulnerability checks after single-package lookup failures, and making dependency graph output project-name aware. (`#1254 <https://github.com/libp2p/py-libp2p/issues/1254>`__)
- Deduplicated repeated `requests` and `types-requests` entries in project dependencies to keep dependency metadata consistent and reduce false duplicate signals in observability reports. (`#1255 <https://github.com/libp2p/py-libp2p/issues/1255>`__)
- Extended ``interop/transport/ping_test.py`` for the libp2p test-plans harness: TLS and WSS transport paths, test-plans JSON dialer output, ``listenerAddr`` Redis coordination, and related timing and compatibility adjustments. (`#1300 <https://github.com/libp2p/py-libp2p/issues/1300>`__)
- Replace the fixed ``trio.sleep(settle_time)`` in the ``subscribed_mesh`` pubsub
  test fixture with deterministic predicate-based polling using ``wait_for()``.
  The fixture now accepts ``ready_timeout`` / ``poll_interval`` and waits until
  every router's mesh for the topic has at least ``min(n - 1, router.degree_low)``
  peers before yielding. (`#1307 <https://github.com/libp2p/py-libp2p/issues/1307>`__)
- Hardened pubsub dummyaccount topology tests against intermittent CI failures by waiting for event-driven network readiness instead of fixed delays. (`#1353 <https://github.com/libp2p/py-libp2p/issues/1353>`__)
- Removed the duplicate ``libp2p/transport/webrtc/_varint.py`` and migrated WebRTC stream and signaling framing onto the shared ``libp2p.utils.varint`` utilities. (`#1355 <https://github.com/libp2p/py-libp2p/issues/1355>`__)
- Widened the ``zeroconf`` dependency range to ``>=0.149.16,<0.151.0`` to allow security and bugfix releases while keeping mDNS discovery on a tested 0.149–0.150 line. (`#1369 <https://github.com/libp2p/py-libp2p/issues/1369>`__)
- Fixed CI lint failure on ``main`` caused by mypy 2.2 ``comparison-overlap`` in the QUIC stream read loop. Reads blocked on ``_receive_event`` still raise ``QUICStreamResetError`` when the stream is reset concurrently. (`#1373 <https://github.com/libp2p/py-libp2p/issues/1373>`__)
- De-flaked the GossipSub v1.1 score-gate test ``test_gossip_gate_filters_peers`` by waiting for event-driven subscription readiness (``Pubsub.wait_for_subscription``) instead of a fixed ``trio.sleep``, which raced on slow CI runners. (`#1401 <https://github.com/libp2p/py-libp2p/issues/1401>`__)
- Declare ``flush_pending_messages`` and ``send_recent_messages`` as optional
  no-op hooks on ``IPubsubRouter`` instead of probing the router with ``hasattr``
  in ``Pubsub``. (`#1403 <https://github.com/libp2p/py-libp2p/issues/1403>`__)
- De-flaked identify-aware GossipSub publish tests by waiting for the subscriber payload instead of a fixed ``trio.sleep``, which raced on slow Windows CI. (`#1406 <https://github.com/libp2p/py-libp2p/issues/1406>`__)
- De-flaked ``test_expiry_removal`` by polling until the background sweeper thread removes the expired entry instead of a fixed ``trio.sleep``, which raced on slow CI runners (integer-second TTL swept on a coarse ~1s thread cadence). (`#1408 <https://github.com/libp2p/py-libp2p/issues/1408>`__)
- De-flaked remaining timed-cache expiry tests by polling until entries expire instead of fixed ``trio.sleep``, and stopped waiting via ``LastSeenCache.has()`` (which refreshes TTL). (`#1428 <https://github.com/libp2p/py-libp2p/issues/1428>`__)
- Stop the two ``TestQUICListenerRaceConditions`` tests from racing on a fixed ``trio.sleep(0.1)``. ``test_multiple_cid_routing_concurrent_load`` and ``test_promotion_race_condition`` now join a nursery around their concurrent tasks so the assertions run only after every task has finished, instead of guessing how long the tasks take. (`#1430 <https://github.com/libp2p/py-libp2p/issues/1430>`__)
- De-flake ``test_circuit_v2_transport_message_routing_through_relay`` by replacing fixed ``trio.sleep`` waits with bounded readiness polls on the actual connection and relay-reservation conditions. (`#1433 <https://github.com/libp2p/py-libp2p/issues/1433>`__)
- ``UdpMux`` can now carry a full aiortc ``RTCPeerConnection``: new ``attach_muxed_connection(pc, mux, conn)`` helper swaps the peer connection's ICE agent for a mux-backed one (including the DTLS ``_recv``/``_send`` bindings) and registers/unregisters the peer address on ICE state changes; ``add_ice_connection`` marks gathering *started* so aiortc's ``gather()`` no longer binds extra sockets; STUN responses (no ``USERNAME``) route by address; peer addresses are learned from STUN checks and outbound sends (latest wins, capped per connection); ``unregister(ufrag)`` drops the learned addresses; malformed STUN-shaped datagrams are delivered to the connection's data path instead of re-raising ``struct.error`` out of the loop. ``webrtc`` extra now requires ``aiortc>=1.15``. (`#1437 <https://github.com/libp2p/py-libp2p/issues/1437>`__)
- De-flaked Kademlia DHT tests by waiting until routing tables are linked instead of using fixed sleeps, which raced on slow CI runners, especially on Windows. (`#1456 <https://github.com/libp2p/py-libp2p/issues/1456>`__)
- Added go-libp2p WebRTC-Direct interop tests: a pinned go-libp2p v0.49 harness
  built on demand (skipped when the Go toolchain is absent) drives our transport
  in both directions and both protocol versions. py -> go is exercised for v1
  and v2; go -> py is xfail pending the inbound stall in #1470. (`#1471 <https://github.com/libp2p/py-libp2p/issues/1471>`__)
- De-flaked GossipSub direct-peer tests by replacing fixed ``trio.sleep`` waits with bounded ``wait_for`` / ``wait_for_peer`` readiness checks. (`#1491 <https://github.com/libp2p/py-libp2p/issues/1491>`__)
- De-flaked pubsub tests by replacing fixed ``trio.sleep`` readiness waits with
  ``wait_for_peer`` / ``wait_for_subscription`` / ``wait_for_mesh`` / payload helpers. (`#1493 <https://github.com/libp2p/py-libp2p/issues/1493>`__)
- De-flaked WebRTC unit/integration tests by replacing fixed ``sleep`` / poll
  synchronization with event-driven waits (``trio``/``asyncio`` Events and
  bounded ``fail_after`` / ``wait_for``). (`#1501 <https://github.com/libp2p/py-libp2p/issues/1501>`__)
- De-flaked ``test_fanout_maintenance`` with event-driven peer/subscription/mesh waits and aligned prune/unsubscribe backoff to avoid GRAFT-flood rejects after resubscribe. (`#1504 <https://github.com/libp2p/py-libp2p/issues/1504>`__)
- Reap the echo example subprocess cleanly in ``test_echo_thin_waist`` so it no longer leaks its stdout pipe (and, on Windows, the child's listener socket): send SIGTERM, ``wait()`` with a timeout, escalate to SIGKILL only if needed, then close the pipe. Previously ``terminate()`` + ``kill()`` without ``wait()``/close left a ``ResourceWarning`` that failed ``windows (3.12, demos)`` under the ``error::ResourceWarning`` guard. (`#1541 <https://github.com/libp2p/py-libp2p/issues/1541>`__)


Miscellaneous Changes
~~~~~~~~~~~~~~~~~~~~~

- `#654 <https://github.com/libp2p/py-libp2p/issues/654>`__, `#1145 <https://github.com/libp2p/py-libp2p/issues/1145>`__, `#1219 <https://github.com/libp2p/py-libp2p/issues/1219>`__, `#1356 <https://github.com/libp2p/py-libp2p/issues/1356>`__, `#1437 <https://github.com/libp2p/py-libp2p/issues/1437>`__


Performance Improvements
~~~~~~~~~~~~~~~~~~~~~~~~

- Improved yamux receive-window updates during partial reads to reduce round-trips in large perf transfers. (`#1344 <https://github.com/libp2p/py-libp2p/issues/1344>`__)


py-libp2p v0.6.0 (2026-02-16)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- Bitswap CIDv1 now uses proper varint encoding for codec values per the multicodec specification. This is a breaking change for CIDs using codecs with value ≥ 128.

  **Summary**

  CIDv1 now uses proper **varint encoding** for codec values, as specified in the
  `multicodec specification <https://github.com/multiformats/multicodec>`_. This
  changes the binary format for CIDs using codecs with values :math:`\ge 128`.

  **Impact**

  - **95% of CIDs unaffected**: Common codecs (``raw``, ``dag-pb``, ``dag-cbor``)
    use values ``< 128``, which encode identically in both the legacy
    single-byte and the new varint formats.
  - **5% of CIDs affected**: Codecs such as ``dag-jose`` (``0x85``),
    ``dag-json`` (``0x129``), and other experimental codecs with values
    :math:`\ge 128` now use multi-byte varint encoding. Their CIDv1 byte layout
    changes and thus their CID *identities* change.

  **Migration Required**

  If you use ``dag-jose``, ``dag-json``, or custom codecs :math:`\ge 128`:

  1. **Identify affected CIDs** using ``detect_cid_encoding_format()`` (in ``libp2p.bitswap.cid``).
  2. **Recompute CIDs** from original data using ``recompute_cid_from_data()`` (in ``libp2p.bitswap.cid``).
  3. **Update storage** (databases, caches, indexes) with the new CIDs.

  **Code Examples**

  *Check if your CIDs are affected*

  .. code-block:: python

     from libp2p.bitswap.cid import detect_cid_encoding_format

     info = detect_cid_encoding_format(your_cid)

     if info["is_breaking"]:
         print(f"CID uses {info['codec_name']} and needs migration")

  *Recompute affected CIDs*

  .. code-block:: python

     from libp2p.bitswap.cid import recompute_cid_from_data

     # old_cid: the existing CID
     # original_data: the original data that was hashed
     new_cid = recompute_cid_from_data(old_cid, original_data)

  *Backward Compatibility*

  Code continues to accept integer codec values for API compatibility:

  .. code-block:: python

     from libp2p.bitswap.cid import CODEC_RAW, compute_cid_v1

     data = b"example"

     # All of these work:
     cid1 = compute_cid_v1(data, codec=0x55)      # int
     cid2 = compute_cid_v1(data, codec="raw")     # str
     cid3 = compute_cid_v1(data, codec=CODEC_RAW) # Code object

(`#1193 <https://github.com/libp2p/py-libp2p/issues/1193>`__)


Bugfixes
~~~~~~~~

- Fixed swarm listener crash on inbound peer negotiation failures by handling security and muxer upgrade exceptions gracefully, allowing the listener to continue accepting new connections. (`#417 <https://github.com/libp2p/py-libp2p/issues/417>`__)
- Fixed peer ID validation by checking the authenticated peer ID immediately after security handshake, failing fast on mismatches instead of later during mux negotiation with misleading errors. (`#429 <https://github.com/libp2p/py-libp2p/issues/429>`__)
- Fixed interoperability issue where generated Ed25519 keys were not always valid curve points, complying with strict ZIP-215 validation. (`#921 <https://github.com/libp2p/py-libp2p/issues/921>`__)
- Fixed yamux listener incorrectly logging errors when peers close connections gracefully after completing protocol exchanges. Clean connection closures (0 bytes received) are now logged at INFO level instead of ERROR level. (`#1084 <https://github.com/libp2p/py-libp2p/issues/1084>`__)
- Fixed MessageCache KeyError crash when async topic validators process the same message concurrently by adding duplicate detection in put() and defensive pop with default None in shift(). (`#1118 <https://github.com/libp2p/py-libp2p/issues/1118>`__)
- Fixed pubsub service crashes when peers disconnect abruptly by properly handling StreamReset exceptions during message writes. (`#1120 <https://github.com/libp2p/py-libp2p/issues/1120>`__)
- Fixed Pubsub._get_in_topic_gossipsub_peers_from_minus to use self.peer_protocol.get(peer_id) instead of direct dictionary access via self.peer_protocol[peer_id]. This safely ignores peers that are partially disconnected during the heartbeat cycle. (`#1124 <https://github.com/libp2p/py-libp2p/issues/1124>`__)
- Fixed TLS certificate interoperability with Rust libp2p by setting BasicConstraints and KeyUsage X.509 extensions to non-critical, allowing cross-implementation compatibility per libp2p TLS spec. (`#1159 <https://github.com/libp2p/py-libp2p/issues/1159>`__)
- Fixed intermittent Windows CI failure in pubsub dummyaccount ring-topology tests by replacing fixed sleep timers with a state-based `wait_for_convergence` helper. Tests now wait until all nodes satisfy the expected condition (or timeout with a clear assertion) instead of relying on platform-sensitive delays, resolving nested ExceptionGroup flakiness on Windows. (`#1164 <https://github.com/libp2p/py-libp2p/issues/1164>`__)
- Fixed WebSocket transport to immediately raise ``IOException`` on connection closure instead of returning empty bytes, preventing retry loops in ``read_exactly()``. Also added graceful error handling in yamux ``send_window_update()`` for connections closed by peers during window updates. (`#1212 <https://github.com/libp2p/py-libp2p/issues/1212>`__)
- Fixed WebSocket transport crashing on IPv6 multiaddrs due to unhandled ``ProtocolLookupError`` in host extraction, and corrected IPv6 dial URL construction to use RFC 3986 bracket notation. (`#1215 <https://github.com/libp2p/py-libp2p/issues/1215>`__)


Features
~~~~~~~~

- Implemented initial network attack simulation framework to support testing against common P2P attacks (e.g. Eclipse attacks). (`#57 <https://github.com/libp2p/py-libp2p/issues/57>`__)
- Enhanced Circuit Relay v2 security by implementing multi-hop prevention, elegantly blocking relay chaining attempts while preserving legitimate client connections. (`#697 <https://github.com/libp2p/py-libp2p/issues/697>`__)
- Added a comprehensive NAT traversal example demonstrating Circuit Relay v2, DCUtR (Direct Connection Upgrade through Relay), and AutoNAT protocols.

  The example includes three scripts in ``examples/nat/``:
  - ``relay.py``: A publicly reachable relay node that facilitates connections between NATed peers
  - ``listener.py``: A NATed peer that advertises via relay and accepts incoming connections
  - ``dialer.py``: A NATed peer that connects through relay and attempts DCUtR hole punching to establish direct connections

  This example demonstrates how two NATed peers can establish communication through a relay and automatically upgrade to a direct connection when possible, while using AutoNAT to detect and report network reachability status. (`#870 <https://github.com/libp2p/py-libp2p/issues/870>`__)
- Added Gossipsub 2.0 support with enhanced peer scoring, adaptive gossip dissemination, and security features.

  This implementation brings py-libp2p to parity with Go and JS libp2p implementations by adding:

  - **Enhanced Peer Scoring**: Comprehensive scoring system with P6 (application-specific) and P7 (IP colocation penalty) parameters, decay mechanisms, and behavioral penalties
  - **Advanced Message Validation**: Topic-specific validation hooks with caching, timeout mechanisms, and async validator support
  - **Adaptive Gossip Dissemination**: Dynamic network parameter adjustment based on network health and peer scores
  - **Security Enhancements**: Protection against spam, Sybil, and Eclipse attacks through rate limiting, IP diversity enforcement, and equivocation detection
  - **Protocol Negotiation**: Support for ``/meshsub/2.0.0`` protocol with backward compatibility to Gossipsub 1.1/1.2
  - **Interoperability**: Full compatibility with existing Go and JS libp2p Gossipsub 2.0 implementations

  The new protocol version enables Python-based libp2p applications to participate in modern, secure pubsub networks with improved resilience against adversarial conditions. (`#920 <https://github.com/libp2p/py-libp2p/issues/920>`__)
- Added an Eclipse attack simulation module with dual-layer architecture (simulation + real integration) and metrics collection framework. (`#950 <https://github.com/libp2p/py-libp2p/issues/950>`__)
- Implemented round-robin load balancing for CircuitV2 relay selection, prioritizing relays with active reservations for more reliable and evenly distributed relay usage. (`#972 <https://github.com/libp2p/py-libp2p/issues/972>`__)
- Added MVP AutoTLS support in TLS stream security. (`#1072 <https://github.com/libp2p/py-libp2p/issues/1072>`__)
- Improved RSA key compatibility with other libp2p implementations, added public key extraction from peer IDs for Ed25519/Secp256k1 keys, and enhanced pubsub connection management to prevent premature peer removal and service crashes. (`#1106 <https://github.com/libp2p/py-libp2p/issues/1106>`__)
- Added IPv6 support for default bind address configuration.

  - IPv6 bind address is configurable via the ``LIBP2P_BIND_V6`` environment variable (default ``::1``). Use ``::`` to listen on all IPv6 interfaces (e.g. for tests).
  - Invalid ``LIBP2P_BIND_V6`` values fall back to the secure default ``::1``.
  - Thin-waist address utilities and examples support both IPv4 and IPv6. (`#1111 <https://github.com/libp2p/py-libp2p/issues/1111>`__)
- Added TLS-enabled bidirectional chat example demonstrating secure peer-to-peer communication with full-duplex messaging capabilities.

  The new example includes:

  - **TLS Server** (``examples/tls/example_tls_server.py``): A TLS-enabled py-libp2p host that acts as a bidirectional chat server, listening for incoming TLS connections and engaging in full-duplex chat sessions where both server and client can send messages simultaneously.

  - **TLS Client** (``examples/tls/example_tls_client.py``): A TLS-enabled client with three operation modes:
    - Echo mode: Simple request-response pattern for testing TLS connections
    - Chat mode: Interactive bidirectional chat for real-time communication
    - Ping mode: Latency testing with round-trip time measurement

  Both examples showcase TLS 1.3 encryption, automatic peer identity verification during TLS handshake, concurrent send/receive operations using async/await patterns, and graceful connection lifecycle management. This provides a practical reference implementation for developers building TLS-enabled py-libp2p applications. (`#1144 <https://github.com/libp2p/py-libp2p/issues/1144>`__)
- Added new test-plan transport test specifications for py-libp2p v0.x to support interoperability testing and validation of transport implementations. (`#1148 <https://github.com/libp2p/py-libp2p/issues/1148>`__)
- Integrate py-multihash v3 API in Bitswap CID module and records validation. Replaces manual multihash construction and exception-based validation with efficient library methods. Improves code maintainability while maintaining 100% backward compatibility. (`#1180 <https://github.com/libp2p/py-libp2p/issues/1180>`__)
- Multicodec integration for Bitswap CIDs: CIDv1 uses varint-encoded codec prefixes (via ``add_prefix()``). New helpers: ``detect_cid_encoding_format()``, ``recompute_cid_from_data()``, and ``analyze_cid_collection()``. See the breaking fragment and codec documentation for impact and migration. (`#1193 <https://github.com/libp2p/py-libp2p/issues/1193>`__)
- Added py-multibase support for peer IDs, DHT keys, and pubsub message IDs with ``ID.to_multibase()``, ``ID.from_multibase()``, ``ID.from_string()``, and a configurable default encoding via ``libp2p.encoding_config``. Backward-compatible with existing base58 peer IDs. (`#1209 <https://github.com/libp2p/py-libp2p/issues/1209>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Standardized logger names across core modules to use ``__name__`` pattern, enabling fine-grained logging control via ``LIBP2P_DEBUG`` environment variable. (`#906 <https://github.com/libp2p/py-libp2p/issues/906>`__)
- Moved dev dependencies from ``[project.optional-dependencies]`` to ``[dependency-groups]`` and reorganized them to remove duplication. (`#1115 <https://github.com/libp2p/py-libp2p/issues/1115>`__)


py-libp2p v0.5.0 (2025-12-21)
-----------------------------

Bugfixes
~~~~~~~~

- Fixed pubsub service crashes when protocol negotiation fails by adding proper exception handling. (`#910 <https://github.com/libp2p/py-libp2p/issues/910>`__)
- Fixed Yamux.accept_stream() hanging indefinitely when connection is closed. (`#930 <https://github.com/libp2p/py-libp2p/issues/930>`__)
- Handle FLAG_FIN & FLAG_RST in TYPE_WINDOW_UPDATE frames (`#931 <https://github.com/libp2p/py-libp2p/issues/931>`__)
- Added peer ID validation in identify_push protocol to prevent forged peer records.

  This security enhancement ensures that the peer ID in signed peer records matches
  the sender's peer ID, preventing peer ID spoofing attacks. This addresses
  CVE-2023-40583 equivalent vulnerability. (`#958 <https://github.com/libp2p/py-libp2p/issues/958>`__)
- Fixed resource scope cleanup in SwarmConn close method to properly release connection resources when connections are closed. (`#1020 <https://github.com/libp2p/py-libp2p/issues/1020>`__)
- Fixed interoperability with rust-libp2p by switching default key generation to Ed25519 and enhancing Yamux to handle data with SYN/ACK frames. (`#1034 <https://github.com/libp2p/py-libp2p/issues/1034>`__)
- Fixed Mplex connection cleanup to properly handle connection closure callbacks, resolving interop test failures with chromium-rust-v0.53. (`#1037 <https://github.com/libp2p/py-libp2p/issues/1037>`__)
- Fixed QUIC interop issue where Go-to-Python ping would fail after identify stream closes. The listener now properly tracks new Connection IDs issued after connection establishment, enabling correct packet routing for subsequent streams. (`#1044 <https://github.com/libp2p/py-libp2p/issues/1044>`__)
- Kademlia DHT API now accepts string keys instead of bytes (``put_value(key: str, ...)``). Fixes UnicodeDecodeError with binary multihash keys. (`#1059 <https://github.com/libp2p/py-libp2p/issues/1059>`__)
- Fixed BasicHost.run() to accept task_status keyword argument for compatibility with modern pytest-trio (>=0.8.0) and trio (>=0.26.0). (`#1071 <https://github.com/libp2p/py-libp2p/issues/1071>`__)
- Fixed QUIC stream direction misclassification that caused server-side errors when handling client-initiated streams. (`#1081 <https://github.com/libp2p/py-libp2p/issues/1081>`__)


Features
~~~~~~~~

- Noise protocol now uses spec-compliant X25519 keys for DH exchange while maintaining Ed25519 keys for libp2p identity signatures. This fixes signature verification failures and ensures compatibility with other libp2p implementations. Updated ``tests/utils/factories.py`` to use separate X25519 keys for Noise static keys and ``libp2p/security/noise/patterns.py`` to properly handle key separation during handshake.

  Full Specification Compliance Achieved:
  Stream Muxers: Added stream_muxers field to NoiseExtensions (spec requirement)
  Legacy Cleanup: Removed non-spec data field from NoiseHandshakePayload
  Protobuf Schema: Updated to match official libp2p/specs/noise
  WebTransport Support: Certificate hash exchange fully implemented

  Beyond Specification - Advanced Features:
  Early Data (0-RTT): Full implementation with handlers and callbacks
  Advanced Rekeying: Configurable policies and statistics
  Static Key Caching: Performance optimizations
  Comprehensive Management: Full handler system for early data (`#591 <https://github.com/libp2p/py-libp2p/issues/591>`__)
- Added fallback mechanism in Kademlia DHT to use connected peers and peerstore when routing table has insufficient peers. (`#905 <https://github.com/libp2p/py-libp2p/issues/905>`__)
- Enhanced WebSocket transport with advanced features including SOCKS proxy support,
  AutoTLS for browser integration, connection management, and comprehensive configuration
  options. The implementation adds production-ready features like connection pooling,
  statistics tracking, and advanced TLS configuration for improved reliability and
  monitoring capabilities. (`#938 <https://github.com/libp2p/py-libp2p/issues/938>`__)
- Added persistent peer storage system with datastore-agnostic backend support.

  The new PersistentPeerStore implementation provides persistent storage for peer data
  (addresses, keys, metadata, protocols, latency metrics) across application restarts.
  This addresses the limitation of the in-memory peerstore that loses all peer information
  when the process restarts.

  Key features:
  - Datastore-agnostic interface supporting multiple backends (SQLite, LevelDB, RocksDB, Memory)
  - Full compatibility with existing IPeerStore interface
  - Automatic persistence of all PeerData fields including last_identified, ttl, and latmap
  - Factory functions for easy creation with different backends
  - Comprehensive test suite and usage examples

  The implementation follows the same architectural pattern as go-libp2p's pstoreds package,
  providing a robust foundation for long-running libp2p applications that need to maintain
  peer information across restarts. (`#946 <https://github.com/libp2p/py-libp2p/issues/946>`__)
- Enhances the `libp2p`` stack with improved peer connection, relay routing, and discovery for resilient networking.

  **Voucher and Signature Verification**
  - Implements voucher and signature verification in ``resources.py``
  - Validates incoming relay vouchers and signatures to ensure proper authorization
  - Prevents misuse of relay resources through secure validation

  **Relay Selection Logic**
  - Implements initial relay selection logic in ``transport.py``
  - Uses basic selection strategies (first-available or round-robin) for relay dialing
  - Introduces sophisticated relay selection with scoring, latency-based metrics, and retry strategies

  **DHT-based Peer Discovery**
  - Implements DHT-based peer discovery using the libp2p DHT
  - Enables dynamic location and connection to peers across the network

  **Relay Reservation and Maintenance**
  - Implements reservation storage and refresh mechanism
  - Tracks active relay reservations and refreshes them before expiry
  - Supports long-lived relayed connections

  **Relay Multiaddr Handling**
  - Adds ``/p2p-circuit/...`` addresses to peerstore for reconnects and discovery
  - Implements proper parsing and handling of relayed multiaddrs
  - Ensures correct validation and usage of ``/p2p-circuit/p2p/...`` paths during dialing

  **CircuitV2Listener Implementation**
  - Implements ``run()`` method in ``CircuitV2Listener``
  - Finalizes listener logic to support incoming relayed connections

  **Testing and Quality**
  - Adds dedicated tests for voucher and signature verification
  - Includes tests for initial and advanced relay selection logic
  - Covers DHT-based peer discovery functionality
  - Tests reservation storage and refresh mechanisms
  - Validates relay multiaddr handling and parsing
  - Tests ``CircuitV2Listener`` functionality
  - Maintains 100% test coverage across all new features
  - Resolves all linting issues and adheres to code quality standards
  - Ensures no regressions in existing functionality (`#996 <https://github.com/libp2p/py-libp2p/issues/996>`__)
- Introduced ``get_transport_addrs()`` method to ``BasicHost`` for retrieving raw transport addresses without the peer ID suffix.
  Refactored ``get_addrs()`` to utilize this new method, maintaining backward compatibility. (`#1073 <https://github.com/libp2p/py-libp2p/issues/1073>`__)
- Adds custom validator support and quorum-based value retrieval to the Kademlia DHT. (`#1095 <https://github.com/libp2p/py-libp2p/issues/1095>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Enhanced QUIC Connection ID management with quinn-inspired improvements:
  - Added sequence number tracking for proper CID retirement ordering
  - Separated initial vs. established CID lookups for better packet routing
  - Improved fallback routing from O(n) to O(1) using reverse address mapping
  - Refactored Connection ID management into a dedicated ConnectionIDRegistry class

  These changes improve robustness, performance, and alignment with proven QUIC implementations. (`#1044 <https://github.com/libp2p/py-libp2p/issues/1044>`__)
- Refactored QUIC Connection ID management into a dedicated ConnectionIDRegistry class, improving code organization and maintainability of the QUIC listener. (`#1046 <https://github.com/libp2p/py-libp2p/issues/1046>`__)
- Upgraded py-libp2p transport ping test to the latest standard. (`#1086 <https://github.com/libp2p/py-libp2p/issues/1086>`__)
- Updated py-multihash dependency from git repository to PyPI version 3.0.0. (`#1102 <https://github.com/libp2p/py-libp2p/issues/1102>`__)


Miscellaneous Changes
~~~~~~~~~~~~~~~~~~~~~

- `#926 <https://github.com/libp2p/py-libp2p/issues/926>`__, `#1039 <https://github.com/libp2p/py-libp2p/issues/1039>`__


py-libp2p v0.4.0 (2025-11-05)
-----------------------------

Bugfixes
~~~~~~~~

- Fix circuit relay hanging issue. (`#767 <https://github.com/libp2p/py-libp2p/issues/767>`__)
- Fixed a typo in the ``negotiate_timeout`` parameter name. (`#908 <https://github.com/libp2p/py-libp2p/issues/908>`__)
- Added IPv4 address validation for LIBP2P_BIND environment variable to prevent invalid addresses from causing runtime errors. Invalid addresses now fallback to the secure default of 127.0.0.1. (`#964 <https://github.com/libp2p/py-libp2p/issues/964>`__)
- Fix type checker error with miniupnpc import by adding type ignore comment. (`#1009 <https://github.com/libp2p/py-libp2p/issues/1009>`__)


Features
~~~~~~~~

- Adds the `StreamState` to the NetStream class to manage the state of network streams more effectively.

  **Stream State Management:**
  - Implements comprehensive stream lifecycle tracking with states: INIT, OPEN, CLOSE_READ, CLOSE_WRITE, CLOSE_BOTH, RESET, ERROR
  - Provides state-based validation to prevent operations on invalid streams (e.g., write-after-close, read-after-reset)
  - Replaces lock-based state management with cooperative concurrency for better performance
  - Adds intelligent error handling that distinguishes between expected stream exceptions and truly unexpected errors

  **ERROR State Implementation:**
  - Implements full ERROR state functionality with prevention, triggers, and recovery mechanisms
  - Adds `is_operational()` method to check if stream can perform I/O operations
  - Adds `recover_from_error()` method to attempt recovery from error state
  - Provides comprehensive error state validation across all stream operations

  **State Transition Summary and Monitoring:**
  - Adds automatic state transition logging for debugging and monitoring
  - Implements `get_state_transition_summary()` method for operational status
  - Implements `get_valid_transitions()` method to show possible next states
  - Implements `get_state_transition_documentation()` for comprehensive state lifecycle info
  - Provides developer-friendly state transition visibility and debugging support

  **Testing and Quality:**
  - Adds 13 dedicated tests for ERROR state functionality covering all scenarios
  - Adds 8 additional tests for state transition functionality
  - Maintains 100% test coverage with 876+ tests passing
  - Resolves all linting issues and maintains code quality standards
  - No regressions introduced - all existing functionality preserved

  Adds the `remove` method to notify the Swarm that a stream has been removed. (`#632 <https://github.com/libp2p/py-libp2p/issues/632>`__)
- Add NAT traversal via UPnP port mapping.

  - Implements automatic port mapping through UPnP-enabled gateways
  - Provides `UpnpManager` class for standalone UPnP operations
  - Integrates UPnP support into BasicHost with `enable_upnp=True` parameter
  - Includes comprehensive example demonstrating UPnP functionality
  - Supports double-NAT detection and proper error handling
  - Automatically cleans up port mappings on shutdown (`#771 <https://github.com/libp2p/py-libp2p/issues/771>`__)
- Added GossipSub 1.2 protocol support to py-libp2p.

  - Implements the `/meshsub/1.2.0` protocol ID
  - Adds support for IDONTWANT control messages for efficient bandwidth usage
  - Maintains backward compatibility with previous GossipSub versions
  - Exposes public `get_message_id()` method in PubSub class
  - Includes comprehensive test coverage for new functionality (`#806 <https://github.com/libp2p/py-libp2p/issues/806>`__)
- Add TLS transport support for libp2p.

  - Implements TLS 1.3 transport with self-signed certificates
  - Adds libp2p identity binding in X.509 extensions
  - Supports peer ID verification through certificate chain
  - Enables ALPN protocol negotiation for stream muxers
  - Provides secure handshake and message encryption
  - Compatible with other libp2p implementations
  - Includes comprehensive test coverage (`#831 <https://github.com/libp2p/py-libp2p/issues/831>`__)
- Circuit-Relay V2 now include signed-peer-records in protobuf schema for secure peer-relay and peer communication. (`#848 <https://github.com/libp2p/py-libp2p/issues/848>`__)
- Implemented Gossipsub v1.1 peer scoring and signed peer records functionality.

  This major update brings py-libp2p into compliance with the Gossipsub v1.1 specification,
  adding comprehensive peer scoring mechanisms and signed peer record validation for peer exchange (PX).

  **Key Features Added:**

  * **Peer Scoring System**: New `PeerScorer` class implementing weighted-decayed counters
    with P1-P4 topic-scoped metrics (time in mesh, first deliveries, mesh deliveries, invalid messages)
    and P5 global behavior penalty scoring.

  * **Score-Based Gates**: Implemented publish acceptance, gossip emission, PX acceptance,
    and graylisting thresholds to control peer behavior based on their scores.

  * **Signed Peer Records**: Enhanced peer exchange (PX) to validate and store signed peer
    records from PRUNE messages, ensuring peer ID matches and updating peerstore accordingly.

  * **Opportunistic Grafting**: Added mesh management hooks that enable opportunistic
    grafting based on median mesh scores to improve network topology.

  * **Protocol Version Detection**: Added `supports_scoring()` method to detect Gossipsub v1.1
    capabilities and enable scoring features only for compatible peers.

  * **Observability**: Comprehensive score statistics via `get_score_stats()` and
    `get_all_peer_scores()` methods for monitoring and debugging peer behavior.

  * **Heartbeat-Driven Decay**: Automatic score decay during heartbeat intervals to
    ensure recent behavior is weighted more heavily than historical data.

  The implementation maintains backward compatibility while providing production-ready
  scoring parameters with conservative defaults. All existing APIs continue to work
  unchanged, with scoring features activated automatically for Gossipsub v1.1 peers.

  This addresses issue #871 and brings py-libp2p in line with other libp2p implementations
  for improved network resilience and attack resistance. (`#872 <https://github.com/libp2p/py-libp2p/issues/872>`__)
- Added the libp2p-records module in reference with go-libp2p-record repo

  - Added the NameSpaceValidator utils in libp2p/records
  - Integrated the PubKey Validators with kad-dht ValueStore interfaces. (`#890 <https://github.com/libp2p/py-libp2p/issues/890>`__)
- Added `Rendezvous` peer discovery module that enables namespace-based peer registration and discovery with automatic refresh capabilities for decentralized peer-to-peer networking. (`#898 <https://github.com/libp2p/py-libp2p/issues/898>`__)
- Added Bitswap protocol implementation for peer-to-peer file sharing with Merkle DAG structure and content addressing. (`#980 <https://github.com/libp2p/py-libp2p/issues/980>`__)
- Implemented timeout enforcement for MplexStream deadline functionality.

  The MplexStream class now properly enforces read and write deadlines using trio.fail_after(),
  preventing operations from hanging indefinitely. The set_deadline(), set_read_deadline(),
  and set_write_deadline() methods now include input validation and return meaningful
  boolean values. TimeoutError exceptions are raised when operations exceed their deadlines.

  This addresses the issue where deadline methods existed but were not actually enforced,
  improving reliability and preventing resource leaks in production applications. (`#984 <https://github.com/libp2p/py-libp2p/issues/984>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added timeouts to CI/CD pipeline to prevent hanging tests.

  - Added 60-minute job timeout to GitHub Actions workflow
  - Added 20-minute pytest timeouts to tox.ini for all test environments
  - Updated Makefile test command with 20-minute timeout
  - Prevents tests from hanging indefinitely in CI/CD (`#977 <https://github.com/libp2p/py-libp2p/issues/977>`__)


Performance Improvements
~~~~~~~~~~~~~~~~~~~~~~~~

- Migrated CI/CD pipeline from pip to uv for improved build performance and faster dependency resolution.

  **Performance Improvements:**
  - Windows wheel tests: 60%+ faster package building
  - Linux lint tests: 14% average improvement
  - Linux interop tests: 6% average improvement
  - Overall CI/CD pipeline: significantly faster execution

  **Technical Changes:**
  - Updated GitHub Actions workflows to use uv instead of pip
  - Modified tox.ini to use uv for package installation
  - Updated scripts to use uv commands
  - Maintained full compatibility with existing test environments (`#997 <https://github.com/libp2p/py-libp2p/issues/997>`__)


py-libp2p v0.3.0 (2025-09-25)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- identify protocol use now prefix-length messages by default. use use_varint_format param for old raw messages (`#761 <https://github.com/libp2p/py-libp2p/issues/761>`__)


Bugfixes
~~~~~~~~

- Improved type safety in `get_mux()` and `get_protocols()` by returning properly typed values instead
  of `Any`. Also updated `identify.py` and `discovery.py` to handle `None` values safely and
  compare protocols correctly. (`#746 <https://github.com/libp2p/py-libp2p/issues/746>`__)
- fixed malformed PeerId in test_peerinfo (`#757 <https://github.com/libp2p/py-libp2p/issues/757>`__)
- Fixed incorrect handling of raw protobuf format in identify protocol. The identify example now properly handles both raw and length-prefixed (varint) message formats, provides better error messages, and displays connection status with peer IDs. Replaced mock-based tests with comprehensive real network integration tests for both formats. (`#778 <https://github.com/libp2p/py-libp2p/issues/778>`__)
- Fixed incorrect handling of raw protobuf format in identify push protocol. The identify push example now properly handles both raw and length-prefixed (varint) message formats, provides better error messages, and displays connection status with peer IDs. Replaced mock-based tests with comprehensive real network integration tests for both formats. (`#784 <https://github.com/libp2p/py-libp2p/issues/784>`__)
- Recompiled protobufs that were out of date and added a `make` rule so that protobufs are always up to date. (`#818 <https://github.com/libp2p/py-libp2p/issues/818>`__)
- Added multiselect type consistency in negotiate method. Updates all the usages of the method. (`#837 <https://github.com/libp2p/py-libp2p/issues/837>`__)
- Fixed message id type inconsistency in handle ihave and message id parsing improvement in handle iwant in pubsub module. (`#843 <https://github.com/libp2p/py-libp2p/issues/843>`__)
- Fix kbucket splitting in routing table when full. Routing table now maintains multiple kbuckets and properly distributes peers as specified by the Kademlia DHT protocol. (`#846 <https://github.com/libp2p/py-libp2p/issues/846>`__)
- Fix multi-address listening bug in swarm.listen()

  - Fix early return in swarm.listen() that prevented listening on all addresses
  - Add comprehensive tests for multi-address listening functionality
  - Ensure all available interfaces are properly bound and connectable (`#863 <https://github.com/libp2p/py-libp2p/issues/863>`__)
- Fixed cross-platform path handling by replacing hardcoded OS-specific
  paths with standardized utilities in core modules and examples. (`#886 <https://github.com/libp2p/py-libp2p/issues/886>`__)
- Exposed timeout method in muxer multistream and updated all the usage. Added testcases to verify that timeout value is passed correctly (`#896 <https://github.com/libp2p/py-libp2p/issues/896>`__)
- enhancement: Add write lock to `YamuxStream` to prevent concurrent write race conditions

  - Implements ReadWriteLock for `YamuxStream` write operations
  - Prevents data corruption from concurrent write operations
  - Read operations remain lock-free due to existing `Yamux` architecture
  - Resolves race conditions identified in Issue #793 (`#897 <https://github.com/libp2p/py-libp2p/issues/897>`__)
- Fix multiaddr dependency to use the last py-multiaddr commit hash to resolve installation issues (`#927 <https://github.com/libp2p/py-libp2p/issues/927>`__)
- Fixed Windows CI/CD tests to use correct Python version instead of hardcoded Python 3.11. test 2 (`#952 <https://github.com/libp2p/py-libp2p/issues/952>`__)
- Fix flaky test_find_node in kad_dht by eliminating race conditions and adding retry mechanism

  - Enhanced dht_pair fixture to force peer discovery during setup, eliminating async race conditions
  - Added retry mechanism with proper type annotations for additional resilience
  - Added pytest-rerunfailures dependency and flaky test marker
  - Resolves intermittent CI failures in tests/core/kad_dht/test_kad_dht.py::test_find_node (`#956 <https://github.com/libp2p/py-libp2p/issues/956>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Improve error message under the function decode_uvarint_from_stream in libp2p/utils/varint.py file (`#760 <https://github.com/libp2p/py-libp2p/issues/760>`__)
- Clarified the requirement for a trailing newline in newsfragments to pass lint checks. (`#775 <https://github.com/libp2p/py-libp2p/issues/775>`__)


Features
~~~~~~~~

- Added experimental WebSocket transport support with basic WS and WSS functionality. This includes:

  - WebSocket transport implementation with trio-websocket backend
  - Support for both WS (WebSocket) and WSS (WebSocket Secure) protocols
  - Basic connection management and stream handling
  - TLS configuration support for WSS connections
  - Multiaddr parsing for WebSocket addresses
  - Integration with libp2p host and peer discovery

  **Note**: This is experimental functionality. Advanced features like proxy support,
  interop testing, and production examples are still in development. See
  https://github.com/libp2p/py-libp2p/discussions/937 for the complete roadmap of missing features. (`#585 <https://github.com/libp2p/py-libp2p/issues/585>`__)
- Added `Bootstrap` peer discovery module that allows nodes to connect to predefined bootstrap peers for network discovery. (`#711 <https://github.com/libp2p/py-libp2p/issues/711>`__)
- Add lock for read/write to avoid interleaving receiving messages in mplex_stream.py (`#748 <https://github.com/libp2p/py-libp2p/issues/748>`__)
- Add logic to clear_peerdata method in peerstore (`#750 <https://github.com/libp2p/py-libp2p/issues/750>`__)
- Added the `Certified Addr-Book` interface supported by `Envelope` and `PeerRecord` class.
  Integrated the signed-peer-record transfer in the identify/push protocols. (`#753 <https://github.com/libp2p/py-libp2p/issues/753>`__)
- add length-prefixed support to identify protocol (`#761 <https://github.com/libp2p/py-libp2p/issues/761>`__)
- Add QUIC transport support for faster, more efficient peer-to-peer connections with native stream multiplexing. (`#763 <https://github.com/libp2p/py-libp2p/issues/763>`__)
- Added Thin Waist address validation utilities (with support for interface enumeration, optimal binding, and wildcard expansion). (`#811 <https://github.com/libp2p/py-libp2p/issues/811>`__)
- KAD-DHT now include signed-peer-records in its protobuf message schema, for more secure peer-discovery. (`#815 <https://github.com/libp2p/py-libp2p/issues/815>`__)
- Added `Random Walk` peer discovery module that enables random peer exploration for improved peer discovery. (`#822 <https://github.com/libp2p/py-libp2p/issues/822>`__)
- Implement closed_stream notification in MyNotifee

  - Add notify_closed_stream method to swarm notification system for proper stream lifecycle management
  - Integrate remove_stream hook in SwarmConn to enable stream closure notifications
  - Add comprehensive tests for closed_stream functionality in test_notify.py
  - Enable stream lifecycle integration for proper cleanup and resource management (`#826 <https://github.com/libp2p/py-libp2p/issues/826>`__)
- Add automatic peer dialing in bootstrap module using trio.Nursery. (`#849 <https://github.com/libp2p/py-libp2p/issues/849>`__)
- Fix type for gossipsub_message_id for consistency and security (`#859 <https://github.com/libp2p/py-libp2p/issues/859>`__)
- Enhanced Swarm networking with retry logic, exponential backoff, and multi-connection support. Added configurable retry mechanisms that automatically recover from transient connection failures using exponential backoff with jitter to prevent thundering herd problems. Introduced connection pooling that allows multiple concurrent connections per peer for improved performance and fault tolerance. Added load balancing across connections and automatic connection health management. All enhancements are fully backward compatible and can be configured through new RetryConfig and ConnectionConfig classes. (`#874 <https://github.com/libp2p/py-libp2p/issues/874>`__)
- Updated all example scripts and core modules to use secure loopback addresses instead of wildcard addresses for network binding.
  The `get_wildcard_address` function and related logic now utilize all available interfaces safely, improving security and consistency across the codebase. (`#885 <https://github.com/libp2p/py-libp2p/issues/885>`__)
- PubSub routers now include signed-peer-records in RPC messages for secure peer-info exchange. (`#889 <https://github.com/libp2p/py-libp2p/issues/889>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- remove FIXME comment since it's obsolete and 32-byte prefix support is there but not enabled by default (`#592 <https://github.com/libp2p/py-libp2p/issues/592>`__)
- Add comprehensive tests for relay_discovery method in circuit_relay_v2 (`#749 <https://github.com/libp2p/py-libp2p/issues/749>`__)
- [mplex] Add timeout and error handling during stream close (`#752 <https://github.com/libp2p/py-libp2p/issues/752>`__)
- fixed a typecheck error using cast in peerinfo.py (`#757 <https://github.com/libp2p/py-libp2p/issues/757>`__)
- Fix raw format reading in identify/push protocol and add comprehensive test coverage for both varint and raw formats (`#761 <https://github.com/libp2p/py-libp2p/issues/761>`__)
- Pin py-multiaddr dependency to specific git commit db8124e2321f316d3b7d2733c7df11d6ad9c03e6 (`#766 <https://github.com/libp2p/py-libp2p/issues/766>`__)
- Make TProtocol as Optional[TProtocol] to keep types consistent in py-libp2p/libp2p/protocol_muxer/multiselect.py (`#770 <https://github.com/libp2p/py-libp2p/issues/770>`__)
- Replace the libp2p.peer.ID cache attributes with functools.cached_property functional decorator. (`#772 <https://github.com/libp2p/py-libp2p/issues/772>`__)
- Yamux RawConnError Logging Refactor - Improved error handling and debug logging (`#784 <https://github.com/libp2p/py-libp2p/issues/784>`__)
- Add Thin Waist address validation utilities and integrate into echo example

  - Add ``libp2p/utils/address_validation.py`` with dynamic interface discovery
  - Implement ``get_available_interfaces()``, ``get_optimal_binding_address()``, and ``expand_wildcard_address()``
  - Update echo example to use dynamic address discovery instead of hardcoded wildcard
  - Add safe fallbacks for environments lacking Thin Waist support
  - Temporarily disable IPv6 support due to libp2p handshake issues (re-enabled later; use ``LIBP2P_BIND_V6`` to configure IPv6 bind address) (`#811 <https://github.com/libp2p/py-libp2p/issues/811>`__)
- The TODO IK patterns in Noise has been deprecated in specs: https://github.com/libp2p/specs/tree/master/noise#handshake-pattern (`#816 <https://github.com/libp2p/py-libp2p/issues/816>`__)
- Remove the already completed TODO tasks in Peerstore:
  TODO: Set up an async task for periodic peer-store cleanup for expired addresses and records.
  TODO: Make proper use of this function (`#819 <https://github.com/libp2p/py-libp2p/issues/819>`__)
- Improved PubsubNotifee integration tests and added failure scenario coverage. (`#855 <https://github.com/libp2p/py-libp2p/issues/855>`__)
- Remove unused upgrade_listener function from transport upgrader

  - Remove unused `upgrade_listener` function from `libp2p/transport/upgrader.py` (Issue 2 from #726)
  - Clean up unused imports related to the removed function
  - Improve code maintainability by removing dead code (`#883 <https://github.com/libp2p/py-libp2p/issues/883>`__)
- Replace magic numbers with named constants and enums for clarity and maintainability

  **Key Changes:**
  - **Introduced type-safe enums** for better code clarity:
  - `RelayRole(Flag)` enum with HOP, STOP, CLIENT roles supporting bitwise combinations (e.g., `RelayRole.HOP | RelayRole.STOP`)
  - `ReservationStatus(Enum)` for reservation lifecycle management (ACTIVE, EXPIRED, REJECTED)
  - **Replaced magic numbers with named constants** throughout the codebase, improving code maintainability and eliminating hardcoded timeout values (15s, 30s, 10s) with descriptive constant names
  - **Added comprehensive timeout configuration system** with new `TimeoutConfig` dataclass supporting component-specific timeouts (discovery, protocol, DCUtR)
  - **Enhanced configurability** of `RelayDiscovery`, `CircuitV2Protocol`, and `DCUtRProtocol` constructors with optional timeout parameters
  - **Improved architecture consistency** with clean configuration flow across all circuit relay components
  - **Backward Compatibility:** All changes maintain full backward compatibility. Existing code continues to work unchanged while new timeout configuration options are available for users who need them. (`#917 <https://github.com/libp2p/py-libp2p/issues/917>`__)


Miscellaneous Changes
~~~~~~~~~~~~~~~~~~~~~

- `#934 <https://github.com/libp2p/py-libp2p/issues/934>`__


Performance Improvements
~~~~~~~~~~~~~~~~~~~~~~~~

- Added throttling for async topic validators in validate_msg, enforcing a
  concurrency limit to prevent resource exhaustion under heavy load. (`#755 <https://github.com/libp2p/py-libp2p/issues/755>`__)


py-libp2p v0.2.9 (2025-07-09)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- Reordered the arguments to ``upgrade_security`` to place ``is_initiator`` before ``peer_id``, and made ``peer_id`` optional.
  This allows the method to reflect the fact that peer identity is not required for inbound connections. (`#681 <https://github.com/libp2p/py-libp2p/issues/681>`__)


Bugfixes
~~~~~~~~

- Add timeout wrappers in:
  1. ``multiselect.py``: ``negotiate`` function
  2. ``multiselect_client.py``: ``select_one_of`` , ``query_multistream_command`` functions
  to prevent indefinite hangs when a remote peer does not respond. (`#696 <https://github.com/libp2p/py-libp2p/issues/696>`__)
- Align stream creation logic with yamux specification (`#701 <https://github.com/libp2p/py-libp2p/issues/701>`__)
- Fixed an issue in ``Pubsub`` where async validators were not handled reliably under concurrency. Now uses a safe aggregator list for consistent behavior. (`#702 <https://github.com/libp2p/py-libp2p/issues/702>`__)


Features
~~~~~~~~

- Added support for ``Kademlia DHT`` in py-libp2p. (`#579 <https://github.com/libp2p/py-libp2p/issues/579>`__)
- Limit concurrency in ``push_identify_to_peers`` to prevent resource congestion under high peer counts. (`#621 <https://github.com/libp2p/py-libp2p/issues/621>`__)
- Store public key and peer ID in peerstore during handshake

  Modified the InsecureTransport class to accept an optional peerstore parameter and updated the handshake process to store the received public key and peer ID in the peerstore when available.

  Added test cases to verify:
  1. The peerstore remains unchanged when handshake fails due to peer ID mismatch
  2. The handshake correctly adds a public key to a peer ID that already exists in the peerstore but doesn't have a public key yet (`#631 <https://github.com/libp2p/py-libp2p/issues/631>`__)
- Fixed several flow-control and concurrency issues in the ``YamuxStream`` class. Previously, stress-testing revealed that transferring data over ``DEFAULT_WINDOW_SIZE`` would break the stream due to inconsistent window update handling and lock management. The fixes include:

  - Removed sending of window updates during writes to maintain correct flow-control.
  - Added proper timeout handling when releasing and acquiring locks to prevent concurrency errors.
  - Corrected the ``read`` function to properly handle window updates for both ``read_until_EOF`` and ``read_n_bytes``.
  - Added event logging at ``send_window_updates`` and ``waiting_for_window_updates`` for better observability. (`#639 <https://github.com/libp2p/py-libp2p/issues/639>`__)
- Added support for ``Multicast DNS`` in py-libp2p (`#649 <https://github.com/libp2p/py-libp2p/issues/649>`__)
- Optimized pubsub publishing to send multiple topics in a single message instead of separate messages per topic. (`#685 <https://github.com/libp2p/py-libp2p/issues/685>`__)
- Optimized pubsub message writing by implementing a write_msg() method that uses pre-allocated buffers and single write operations, improving performance by eliminating separate varint prefix encoding and write operations in FloodSub and GossipSub. (`#687 <https://github.com/libp2p/py-libp2p/issues/687>`__)
- Added peer exchange and backoff logic as part of Gossipsub v1.1 upgrade (`#690 <https://github.com/libp2p/py-libp2p/issues/690>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added sparse connect utility function to pubsub test utilities for creating test networks with configurable connectivity. (`#679 <https://github.com/libp2p/py-libp2p/issues/679>`__)
- Added comprehensive tests for pubsub connection utility functions to verify degree limits are enforced, excess peers are handled correctly, and edge cases (degree=0, negative values, empty lists) are managed gracefully. (`#707 <https://github.com/libp2p/py-libp2p/issues/707>`__)
- Added extra tests for identify push concurrency cap under high peer load (`#708 <https://github.com/libp2p/py-libp2p/issues/708>`__)


Miscellaneous Changes
~~~~~~~~~~~~~~~~~~~~~

- `#678 <https://github.com/libp2p/py-libp2p/issues/678>`__, `#684 <https://github.com/libp2p/py-libp2p/issues/684>`__


py-libp2p v0.2.8 (2025-06-10)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- The `NetStream.state` property is now async and requires `await`. Update any direct state access to use `await stream.state`. (`#300 <https://github.com/libp2p/py-libp2p/issues/300>`__)


Bugfixes
~~~~~~~~

- Added proper state management and resource cleanup to `NetStream`, fixing memory leaks and improved error handling. (`#300 <https://github.com/libp2p/py-libp2p/issues/300>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Updated examples to automatically use random port, when `-p` flag is not given (`#661 <https://github.com/libp2p/py-libp2p/issues/661>`__)


Features
~~~~~~~~

- Allow passing `listen_addrs` to `new_swarm` to customize swarm listening behavior. (`#616 <https://github.com/libp2p/py-libp2p/issues/616>`__)
- Feature: Support for sending `ls` command over `multistream-select` to list supported protocols from remote peer.
  This allows inspecting which protocol handlers a peer supports at runtime. (`#622 <https://github.com/libp2p/py-libp2p/issues/622>`__)
- implement AsyncContextManager for IMuxedStream to support async with (`#629 <https://github.com/libp2p/py-libp2p/issues/629>`__)
- feat: add method to compute time since last message published by a peer and remove fanout peers based on ttl. (`#636 <https://github.com/libp2p/py-libp2p/issues/636>`__)
- implement blacklist management for `pubsub.Pubsub` with methods to get, add, remove, check, and clear blacklisted peer IDs. (`#641 <https://github.com/libp2p/py-libp2p/issues/641>`__)
- fix: remove expired peers from peerstore based on TTL (`#650 <https://github.com/libp2p/py-libp2p/issues/650>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Modernizes several aspects of the project, notably using ``pyproject.toml`` for project info instead of ``setup.py``, using ``ruff`` to replace several separate linting tools, and ``pyrefly`` in addition to ``mypy`` for typing. Also includes changes across the codebase to conform to new linting and typing rules. (`#618 <https://github.com/libp2p/py-libp2p/issues/618>`__)


Removals
~~~~~~~~

- Removes support for python 3.9 and updates some code conventions, notably using ``|`` operator in typing instead of ``Optional`` or ``Union`` (`#618 <https://github.com/libp2p/py-libp2p/issues/618>`__)


py-libp2p v0.2.7 (2025-05-22)
-----------------------------

Bugfixes
~~~~~~~~

- ``handler()`` inside ``TCPListener.listen()`` does not catch exceptions thrown during handshaking steps (from ``Sawrm``).
  These innocuous exceptions will become fatal and crash the process if not handled. (`#586 <https://github.com/libp2p/py-libp2p/issues/586>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Fixed the `contributing.rst` file to include the Libp2p Discord Server Link. (`#592 <https://github.com/libp2p/py-libp2p/issues/592>`__)


Features
~~~~~~~~

- Added support for the Yamux stream multiplexer (/yamux/1.0.0) as the preferred option, retaining Mplex (/mplex/6.7.0) for backward compatibility. (`#534 <https://github.com/libp2p/py-libp2p/issues/534>`__)
- added ``direct peers`` as part of gossipsub v1.1 upgrade. (`#594 <https://github.com/libp2p/py-libp2p/issues/594>`__)
- Feature: Logging in py-libp2p via env vars (`#608 <https://github.com/libp2p/py-libp2p/issues/608>`__)
- Added support for multiple-error formatting in the `MultiError` class. (`#613 <https://github.com/libp2p/py-libp2p/issues/613>`__)


py-libp2p v0.2.6 (2025-05-12)
-----------------------------

Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Expand the Introduction section in the documentation with a detailed overview of Py-libp2p. (`#560 <https://github.com/libp2p/py-libp2p/issues/560>`__)


Features
~~~~~~~~

- Added identify-push protocol implementation and examples to demonstrate how peers can proactively push their identity information to other peers when it changes. (`#552 <https://github.com/libp2p/py-libp2p/issues/552>`__)
- Added AutoNAT protocol (`#561 <https://github.com/libp2p/py-libp2p/issues/561>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Bumps dependency to ``protobuf>=6.30.1``. (`#576 <https://github.com/libp2p/py-libp2p/issues/576>`__)
- Removes old interop tests, creates placeholders for new ones, and turns on interop testing in CI. (`#588 <https://github.com/libp2p/py-libp2p/issues/588>`__)


py-libp2p v0.2.5 (2025-04-14)
-----------------------------

Bugfixes
~~~~~~~~

- Fixed flaky test_simple_last_seen_cache by adding a retry loop for reliable expiry detection across platforms. (`#558 <https://github.com/libp2p/py-libp2p/issues/558>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Added install and getting started documentation. (`#559 <https://github.com/libp2p/py-libp2p/issues/559>`__)


Features
~~~~~~~~

- Added a ``pub-sub`` example having ``gossipsub`` as the router to demonstrate how to use the pub-sub module in py-libp2p. (`#515 <https://github.com/libp2p/py-libp2p/issues/515>`__)
- Added documentation on how to add examples to the libp2p package. (`#550 <https://github.com/libp2p/py-libp2p/issues/550>`__)
- Added Windows-specific development setup instructions to `docs/contributing.rst`. (`#559 <https://github.com/libp2p/py-libp2p/issues/559>`__)


py-libp2p v0.2.4 (2025-03-27)
-----------------------------

Bugfixes
~~~~~~~~

- Added Windows compatibility by using coincurve instead of fastecdsa on Windows platforms (`#507 <https://github.com/libp2p/py-libp2p/issues/507>`__)


py-libp2p v0.2.3 (2025-03-27)
-----------------------------

Bugfixes
~~~~~~~~

- Fixed import path in the examples to use updated `net_stream` module path, resolving ModuleNotFoundError when running the examples. (`#513 <https://github.com/libp2p/py-libp2p/issues/513>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Updates ``Feature Breakdown`` in ``README`` to more closely match the list of standard modules. (`#498 <https://github.com/libp2p/py-libp2p/issues/498>`__)
- Adds detailed Sphinx-style docstrings to ``abc.py``. (`#535 <https://github.com/libp2p/py-libp2p/issues/535>`__)


Features
~~~~~~~~

- Improved the implementation of the identify protocol and enhanced test coverage to ensure proper functionality and network layer address delegation. (`#358 <https://github.com/libp2p/py-libp2p/issues/358>`__)
- Adds the ability to check connection status of a peer in the peerstore. (`#420 <https://github.com/libp2p/py-libp2p/issues/420>`__)
- implemented ``timed_cache`` module which will allow to implement ``seen_ttl`` configurable param for pubsub and protocols extending it. (`#518 <https://github.com/libp2p/py-libp2p/issues/518>`__)
- Added a maximum RSA key size limit of 4096 bits to prevent resource exhaustion attacks.Consolidated validation logic to use a single error message source and
  added tests to catch invalid key sizes (including negative values). (`#523 <https://github.com/libp2p/py-libp2p/issues/523>`__)
- Added automated testing of ``demo`` applications as part of CI to prevent demos from breaking silently. Tests are located in `tests/core/examples/test_examples.py`. (`#524 <https://github.com/libp2p/py-libp2p/issues/524>`__)
- Added an example implementation of the identify protocol to demonstrate its usage and help users understand how to properly integrate it into their libp2p applications. (`#536 <https://github.com/libp2p/py-libp2p/issues/536>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- moved all interfaces to ``libp2p.abc`` along with all libp2p custom types to ``libp2p.custom_types``. (`#228 <https://github.com/libp2p/py-libp2p/issues/228>`__)
- moved ``libp2p/tools/factories`` to ``tests``. (`#503 <https://github.com/libp2p/py-libp2p/issues/503>`__)
- Fixes broken CI lint run, bumps ``pre-commit-hooks`` version to ``5.0.0`` and ``mdformat`` to ``0.7.22``. (`#522 <https://github.com/libp2p/py-libp2p/issues/522>`__)
- Rebuilds protobufs with ``protoc v30.1``. (`#542 <https://github.com/libp2p/py-libp2p/issues/542>`__)
- Moves ``pubsub`` testing tools from ``libp2p.tools`` and ``factories`` from ``tests`` to ``tests.utils``. (`#543 <https://github.com/libp2p/py-libp2p/issues/543>`__)


py-libp2p v0.2.2 (2025-02-20)
-----------------------------

Bugfixes
~~~~~~~~

- - This fix issue #492 adding a missing break statement that lowers GIL usage from 99% to 0%-2%. (`#492 <https://github.com/libp2p/py-libp2p/issues/492>`__)


Features
~~~~~~~~

- Create entry points for demos to be run directly from installed package (`#490 <https://github.com/libp2p/py-libp2p/issues/490>`__)
- Merge template, adding python 3.13 to CI checks. (`#496 <https://github.com/libp2p/py-libp2p/issues/496>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Drop CI runs for python 3.8, run ``pyupgrade`` to bring code up to python 3.9. (`#497 <https://github.com/libp2p/py-libp2p/issues/497>`__)
- Rename ``typing.py`` to ``custom_types.py`` for clarity. (`#500 <https://github.com/libp2p/py-libp2p/issues/500>`__)


py-libp2p v0.2.1 (2024-12-20)
-----------------------------

Bugfixes
~~~~~~~~

- Added missing check to reject messages claiming to be from ourselves but not locally published in pubsub's ``push_msg`` function (`#413 <https://github.com/libp2p/py-libp2p/issues/413>`__)
- Added missing check in ``add_addrs`` function for duplicate addresses in ``peerdata`` (`#485 <https://github.com/libp2p/py-libp2p/issues/485>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- added missing details of params in ``IPubsubRouter`` (`#486 <https://github.com/libp2p/py-libp2p/issues/486>`__)


Features
~~~~~~~~

- Added ``PingService`` class in ``host/ping.py`` which can be used to initiate ping requests to peers and added tests for the same (`#344 <https://github.com/libp2p/py-libp2p/issues/344>`__)
- Added ``get_connected_peers`` method in class ``IHost`` which can be used to get a list of peer ids of currently connected peers (`#419 <https://github.com/libp2p/py-libp2p/issues/419>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Update ``sphinx_rtd_theme`` options and drop pdf build of docs (`#481 <https://github.com/libp2p/py-libp2p/issues/481>`__)
- Update ``trio`` package version dependency (`#482 <https://github.com/libp2p/py-libp2p/issues/482>`__)


py-libp2p v0.2.0 (2024-07-09)
-----------------------------

Breaking Changes
~~~~~~~~~~~~~~~~

- Drop support for ``python<3.8`` (`#447 <https://github.com/libp2p/py-libp2p/issues/447>`__)
- Drop dep for unmaintained ``async-service`` and copy relevant functions into a local tool of the same name (`#467 <https://github.com/libp2p/py-libp2p/issues/467>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Move contributing and history info from README to docs (`#454 <https://github.com/libp2p/py-libp2p/issues/454>`__)
- Display example usage and full code in docs (`#466 <https://github.com/libp2p/py-libp2p/issues/466>`__)


Features
~~~~~~~~

- Add basic support for ``python3.8, 3.9, 3.10, 3.11, 3.12`` (`#447 <https://github.com/libp2p/py-libp2p/issues/447>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Merge updates from ethereum python project template, including using ``pre-commit`` for linting, change name of ``master`` branch to ``main``, lots of linting changes (`#447 <https://github.com/libp2p/py-libp2p/issues/447>`__)
- Fix docs CI, drop ``bumpversion`` for ``bump-my-version``, reorg tests (`#454 <https://github.com/libp2p/py-libp2p/issues/454>`__)
- Turn ``mypy`` checks on and remove ``async_generator`` dependency (`#464 <https://github.com/libp2p/py-libp2p/issues/464>`__)
- Convert ``KeyType`` enum to use ``protobuf.KeyType`` options rather than ints, rebuild protobufs to include ``ECC_P256`` (`#465 <https://github.com/libp2p/py-libp2p/issues/465>`__)
- Bump to ``mypy==1.10.0``, run ``pre-commit`` local hook instead of ``mirrors-mypy`` (`#472 <https://github.com/libp2p/py-libp2p/issues/472>`__)
- Bump ``protobufs`` dep to ``>=5.27.2`` and rebuild protobuf definition with ``protoc==27.2`` (`#473 <https://github.com/libp2p/py-libp2p/issues/473>`__)


Removals
~~~~~~~~

- Drop ``async-exit-stack`` dep, as of py37 can import ``AsyncExitStack`` from contextlib, also open ``pynacl`` dep to bottom pin only (`#468 <https://github.com/libp2p/py-libp2p/issues/468>`__)


libp2p v0.1.5 (2020-03-25)
---------------------------

Features
~~~~~~~~

- Dial all multiaddrs stored for a peer when attempting to connect (not just the first one in the peer store). (`#386 <https://github.com/libp2p/py-libp2p/issues/386>`__)
- Migrate transport stack to trio-compatible code. Merge in #404. (`#396 <https://github.com/libp2p/py-libp2p/issues/396>`__)
- Migrate network stack to trio-compatible code. Merge in #404. (`#397 <https://github.com/libp2p/py-libp2p/issues/397>`__)
- Migrate host, peer and protocols stacks to trio-compatible code. Merge in #404. (`#398 <https://github.com/libp2p/py-libp2p/issues/398>`__)
- Migrate muxer and security transport stacks to trio-compatible code. Merge in #404. (`#399 <https://github.com/libp2p/py-libp2p/issues/399>`__)
- Migrate pubsub stack to trio-compatible code. Merge in #404. (`#400 <https://github.com/libp2p/py-libp2p/issues/400>`__)
- Fix interop tests w/ new trio-style code. Merge in #404. (`#401 <https://github.com/libp2p/py-libp2p/issues/401>`__)
- Fix remainder of test code w/ new trio-style code. Merge in #404. (`#402 <https://github.com/libp2p/py-libp2p/issues/402>`__)
- Add initial infrastructure for `noise` security transport. (`#405 <https://github.com/libp2p/py-libp2p/issues/405>`__)
- Add `PatternXX` of `noise` security transport. (`#406 <https://github.com/libp2p/py-libp2p/issues/406>`__)
- The `msg_id` in a pubsub message is now configurable by the user of the library. (`#410 <https://github.com/libp2p/py-libp2p/issues/410>`__)


Bugfixes
~~~~~~~~

- Use `sha256` when calculating a peer's ID from their public key in Kademlia DHTs. (`#385 <https://github.com/libp2p/py-libp2p/issues/385>`__)
- Store peer ids in ``set`` instead of ``list`` and check if peer id exists in ``dict`` before accessing to prevent ``KeyError``. (`#387 <https://github.com/libp2p/py-libp2p/issues/387>`__)
- Do not close a connection if it has been reset. (`#394 <https://github.com/libp2p/py-libp2p/issues/394>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add support for `fastecdsa` on windows (and thereby supporting windows installation via `pip`) (`#380 <https://github.com/libp2p/py-libp2p/issues/380>`__)
- Prefer f-string style formatting everywhere except logging statements. (`#389 <https://github.com/libp2p/py-libp2p/issues/389>`__)
- Mark `lru` dependency as third-party to fix a windows inconsistency. (`#392 <https://github.com/libp2p/py-libp2p/issues/392>`__)
- Bump `multiaddr` dependency to version `0.0.9` so that multiaddr objects are hashable. (`#393 <https://github.com/libp2p/py-libp2p/issues/393>`__)
- Remove incremental mode of mypy to disable some warnings. (`#403 <https://github.com/libp2p/py-libp2p/issues/403>`__)


libp2p v0.1.4 (2019-12-12)
--------------------------

Features
~~~~~~~~

- Added support for Python 3.6 (`#372 <https://github.com/libp2p/py-libp2p/issues/372>`__)
- Add signing and verification to pubsub (`#362 <https://github.com/libp2p/py-libp2p/issues/362>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Refactor and cleanup gossipsub (`#373 <https://github.com/libp2p/py-libp2p/issues/373>`__)


libp2p v0.1.3 (2019-11-27)
--------------------------

Bugfixes
~~~~~~~~

- Handle Stream* errors (like ``StreamClosed``) during calls to ``stream.write()`` and
  ``stream.read()`` (`#350 <https://github.com/libp2p/py-libp2p/issues/350>`__)
- Relax the protobuf dependency to play nicely with other libraries. It was pinned to 3.9.0, and now
  permits v3.10 up to (but not including) v4. (`#354 <https://github.com/libp2p/py-libp2p/issues/354>`__)
- Fixes KeyError when peer in a stream accidentally closes and resets the stream, because handlers
  for both will try to ``del streams[stream_id]`` without checking if the entry still exists. (`#355 <https://github.com/libp2p/py-libp2p/issues/355>`__)


Improved Documentation
~~~~~~~~~~~~~~~~~~~~~~

- Use Sphinx & autodoc to generate docs, now available on `py-libp2p.readthedocs.io <https://py-libp2p.readthedocs.io>`_ (`#318 <https://github.com/libp2p/py-libp2p/issues/318>`__)


Internal Changes - for py-libp2p Contributors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added Makefile target to test a packaged version of libp2p before release. (`#353 <https://github.com/libp2p/py-libp2p/issues/353>`__)
- Move helper tools from ``tests/`` to ``libp2p/tools/``, and some mildly-related cleanups. (`#356 <https://github.com/libp2p/py-libp2p/issues/356>`__)


Miscellaneous changes
~~~~~~~~~~~~~~~~~~~~~

- `#357 <https://github.com/libp2p/py-libp2p/issues/357>`__


v0.1.2
--------------

Welcome to the great beyond, where changes were not tracked by release...
