Filecoin Network Parity and Interop for py-libp2p
==================================================

This page documents how ``py-libp2p`` currently lines up with Lotus and Forest
networking behavior, and how to reproduce the current interoperability checks.

Scope and evidence
------------------

This page is scoped to Filecoin-facing networking behavior, not full node
consensus behavior. The evidence base for the audit comes from:

- Lotus ``v1.35.0`` networking defaults and modules.
- Forest ``0.32.2`` networking defaults and discovery/peer-management code.
- The current ``py-libp2p`` branch state plus the Filecoin DX examples added in
  Module 5.

Normative references:

- `Lotus libp2p host defaults <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/modules/lp2p/libp2p.go>`_
- `Lotus config defaults <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/config/def.go>`_
- `Forest libp2p configuration <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/config.rs>`_
- `Forest discovery behaviour <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/discovery.rs>`_

Network parity audit
--------------------

.. list-table::
   :header-rows: 1

   * - Concern
     - Lotus / Forest expectation
     - py-libp2p state
     - Parity status
     - Practical implication
     - Suggested next step
   * - Listen address defaults
     - Lotus listens on TCP, QUIC, and WebTransport by default; Forest listens on TCP and QUIC.
     - ``py-libp2p`` defaults to TCP unless QUIC or another transport is explicitly selected.
     - different
     - Filecoin operators should not assume QUIC/WebTransport parity from generic host defaults.
     - Document Filecoin-specific listen-address recommendations instead of changing the global default in this module.
   * - Transport and security stack order
     - Lotus offers Noise and TLS, with configurable preference; Forest composes TCP/QUIC with Noise and identify/discovery services.
     - ``py-libp2p`` currently prefers Noise, keeps TLS as fallback, and reports negotiated transport/security/muxer metadata during interop probes.
     - partial
     - Core interoperability works, but the stack breadth and ordering differ from Filecoin node defaults.
     - Keep defaults stable and publish the recommended Filecoin-oriented transport/security settings.
   * - Muxer defaults
     - Lotus explicitly wires Yamux; Forest uses libp2p swarm configuration with long-lived connections and QUIC where available.
     - ``py-libp2p`` prefers Yamux and retains Mplex fallback.
     - partial
     - TCP interop is fine, but generic fallback behavior still differs from narrower Filecoin defaults.
     - Keep Yamux-first and record negotiated muxer metadata in interop outputs.
   * - Connection manager thresholds and grace period
     - Lotus defaults to ``low=150``, ``high=180``, ``grace=20s``; Forest defaults to ``target_peer_count=75``.
     - ``py-libp2p`` defaults to ``min=50``, ``low=100``, ``high=550``, ``max=600``, ``grace=20s``.
     - different
     - Generic py-libp2p limits are much looser than current Filecoin expectations.
     - Record the difference and propose Filecoin-specific recommended configs in docs/artifacts.
   * - Resource manager behavior
     - Lotus conditionally enables autoscaled resource limits and allowlists bootstrap addresses; Forest relies more on behaviour-level limits and peer management.
     - ``py-libp2p`` has a simpler resource manager and does not mirror Lotus autoscaling or bootstrap allowlisting.
     - different
     - Long-running Filecoin services need explicit resource planning instead of assuming Lotus-like defaults.
     - Treat this as a follow-up reliability/resource-management area rather than changing defaults here.
   * - Discovery stack
     - Lotus and Forest both rely on Kademlia and NAT-related behaviour; Forest also wires identify, AutoNAT, and UPnP directly into discovery.
     - ``py-libp2p`` has discovery primitives, but the Filecoin examples currently use runtime bootstrap dialing as the primary interop workflow.
     - different
     - Public-network smoke testing is possible today, but full lifecycle parity is not implied.
     - Keep discovery gaps explicit and focus this module on reproducible interop evidence.
   * - Peer protection and bad-peer handling
     - Lotus protects bootstrap/configured peers via the connection manager; Forest keeps protected peers and an explicit bad-peer/ban set in the peer manager.
     - ``py-libp2p`` supports protected peers and connection tagging, but does not model Filecoin peer availability and bans the same way.
     - partial
     - Application code still needs to decide which peers are protected and how to treat degraded peers.
     - Document the gap and keep the runtime probe outputs explicit about failure modes.
   * - DHT protocol naming and filters
     - Lotus uses Filecoin-specific DHT protocol naming and public query/routing-table filters; Forest configures Filecoin-specific Kademlia protocol strings.
     - ``py-libp2p`` exposes the Filecoin DHT helper, but does not mirror Lotus routing-filter behavior.
     - partial
     - Filecoin DHT naming is available, but routing/filter parity is not complete.
     - Keep the DHT helper and document the behavioural gap.

Normative references:

- `Lotus transport stack <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/modules/lp2p/transport.go>`_
- `Lotus resource manager <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/modules/lp2p/rcmgr.go>`_
- `Forest peer manager <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/peer_manager.rs>`_
- `go-libp2p connection manager defaults <https://pkg.go.dev/github.com/libp2p/go-libp2p/p2p/net/connmgr>`_

Preferred controlled workflow
-----------------------------

The preferred workflow is to run the Filecoin demos against a Lotus or Forest
node whose multiaddr you control.

1. Start Lotus or Forest with a reachable libp2p address.
2. Capture an explicit ``/.../p2p/<peer-id>`` multiaddr for that node.
3. Run the connect probe:

   .. code-block:: console

      $ filecoin-connect-demo --peer /ip4/203.0.113.10/tcp/24001/p2p/12D3KooW... --json

4. Run the ping/identify probe:

   .. code-block:: console

      $ filecoin-ping-identify-demo --peer /ip4/203.0.113.10/tcp/24001/p2p/12D3KooW... --ping-count 3 --json

5. If the node exposes Filecoin gossip on the public network, run the observer smoke test separately:

   .. code-block:: console

      $ filecoin-pubsub-demo --network mainnet --seconds 20 --json

The controlled workflow is preferred because it gives stable evidence for the
negotiated transport, security protocol, muxer, and advertised Filecoin
protocol set.

Normative references:

- `Lotus bootstrap and networking configuration <https://lotus.filecoin.io/lotus/configure/bootstrap/>`_
- `Forest source tree <https://github.com/ChainSafe/forest/tree/v0.32.2/src/libp2p>`_

Secondary public-network smoke workflow
---------------------------------------

When no controlled Lotus/Forest node is available, the Filecoin bootstrap set
can still be used for quick public-network smoke checks.

.. code-block:: console

   $ filecoin-connect-demo --network mainnet --resolve-dns --json
   $ filecoin-ping-identify-demo --network mainnet --resolve-dns --json
   $ filecoin-pubsub-demo --network mainnet --seconds 5 --json

This workflow is intentionally weaker evidence than the controlled workflow:
public peers may refuse a stream, negotiate a different transport than the one
observed on the previous run, or send malformed gossip control IDs that are
handled defensively by the observer.

Normative references:

- `Filecoin node implementations overview <https://docs.filecoin.io/nodes/implementations>`_
- `Filecoin network interface <https://spec.filecoin.io/systems/filecoin_nodes/network/>`_

Interoperability matrix
-----------------------

.. list-table::
   :header-rows: 1

   * - Case
     - Target
     - Current result
     - Evidence path
     - Notes
   * - Public bootstrap connect
     - Public Filecoin bootstrap peers
     - pass
     - ``filecoin-connect-demo`` JSON output with connection metadata
     - Confirms runtime bootstrap dialing and negotiated transport/security capture.
   * - Public ping + identify
     - Public Filecoin peers that accept identify and ping
     - pass
     - ``filecoin-ping-identify-demo`` JSON output
     - Confirms advertised Filecoin protocol IDs plus negotiated transport/security/muxer metadata.
   * - Lotus identify + ping (controlled)
     - Operator-supplied Lotus node
     - partial
     - Explicit-peer probe steps from the controlled workflow
     - Reproducible, but not launched in CI by this module.
   * - Forest identify + ping (controlled)
     - Operator-supplied Forest node
     - partial
     - Explicit-peer probe steps from the controlled workflow
     - Reproducible, but not launched in CI by this module.
   * - Read-only Filecoin gossipsub observer
     - Public Filecoin gossip peers
     - partial
     - ``filecoin-pubsub-demo`` observer snapshot plus live logs
     - Safe observer mode only; stream negotiation or malformed-control warnings are expected on some peers.
   * - Hello runtime exchange
     - Lotus / Forest nodes
     - expected_gap
     - Protocol constant and identify advertisement only
     - The runtime Hello exchange is intentionally not implemented in this module.
   * - ChainExchange request/response
     - Lotus / Forest nodes
     - expected_gap
     - Protocol constant and identify advertisement only
     - Full request/response behavior remains a follow-up item.

Normative references:

- `Lotus hello protocol <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/hello/hello.go>`_
- `Lotus chain exchange protocol <https://github.com/filecoin-project/lotus/blob/v1.35.0/chain/exchange/protocol.go>`_
- `Forest chain exchange behaviour <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/chain_exchange/behaviour.rs>`_

Current gaps and expected failure modes
---------------------------------------

The immediate gaps that this module keeps explicit are:

- Hello runtime behavior is still unimplemented.
- ChainExchange request/response behavior is still unimplemented.
- Generic ``py-libp2p`` connection/resource defaults do not match current
  Filecoin node defaults.
- Read-only gossipsub observation can succeed while still encountering
  peer-specific stream negotiation failures or malformed control-message IDs.

Expected failure modes recorded by the demos and artifact include:

- connection or identify/ping failure against a specific remote peer.
- gossipsub stream negotiation failure on a subset of public peers.
- malformed IHAVE/IWANT control-message IDs being logged and skipped instead of crashing.

Normative references:

- `Lotus discovery timeout handling <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/modules/lp2p/discovery.go>`_
- `Forest discovery and peer availability handling <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/discovery.rs>`_
- `Forest peer protection and bans <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/peer_manager.rs>`_
