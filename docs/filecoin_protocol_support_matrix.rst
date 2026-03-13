Filecoin Protocol Support Matrix
================================

This page records protocol-level support and gaps for the current
``libp2p.filecoin`` DX layer. It complements :doc:`filecoin_architecture_positioning`
and the constant/value parity notes in ``docs/filecoin/parity_matrix.md``. The
architecture page explains where ``py-libp2p`` fits, the parity matrix captures
value lineage, and this page records what is operational today versus what
remains intentionally out of scope.

Summary matrix
--------------

.. list-table::
   :header-rows: 1

   * - Concern
     - Status
     - Priority
   * - identify
     - ``implemented``
     -
   * - ping
     - ``implemented``
     -
   * - hello protocol ID
     - ``implemented``
     -
   * - hello runtime / wire behavior
     - ``missing``
     - ``P1``
   * - chain exchange protocol ID
     - ``implemented``
     -
   * - chain exchange request/response behavior
     - ``missing``
     - ``P1``
   * - gossipsub protocol negotiation
     - ``implemented``
     -
   * - Filecoin topic naming
     - ``implemented``
     -
   * - Filecoin message ID function
     - ``implemented``
     -
   * - score thresholds
     - ``implemented``
     -
   * - full topic scoring parity
     - ``partial``
     - ``P2``
   * - bootstrapper / PX / direct-peer behavior
     - ``partial``
     - ``P2``
   * - drand / F3 topic handling
     - ``missing``
     - ``P3``
   * - bitswap note
     - ``out_of_scope``
     -

Core diagnostics surfaces
-------------------------

Upstream references for this section:

- `Lotus hello handler waits for identify protocol state before proceeding <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/hello/hello.go>`_
- `Forest identify and ping events in the libp2p service <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/service.rs>`_

Identify
~~~~~~~~

- Status: ``implemented``
- Upstream evidence: Lotus waits for identify-populated protocol state before
  proceeding with hello stream handling; Forest evaluates identify protocol
  support before allowing Filecoin peers further into the networking stack.
- py-libp2p evidence: ``examples/filecoin/filecoin_ping_identify_demo.py``.
- Current practical support: ``py-libp2p`` can connect to peers, run identify,
  and report whether peers advertise Filecoin hello and chain exchange support.
- Missing pieces / failure modes: identify only confirms advertised protocol
  support; it does not provide Filecoin hello or chain exchange behavior by
  itself.
- Recommended next step: keep identify as the first-line diagnostics surface and
  use the dedicated hello/chain exchange rows below to track runtime parity.

Ping
~~~~

- Status: ``implemented``
- Upstream evidence: Forest handles ping events directly inside the libp2p
  service and records RTT/failure outcomes.
- py-libp2p evidence: ``examples/filecoin/filecoin_ping_identify_demo.py``.
- Current practical support: ``py-libp2p`` can run ping-based peer diagnostics
  against Filecoin peers and report RTT summaries.
- Missing pieces / failure modes: ping validates connectivity only; it is not a
  substitute for Filecoin protocol interoperability.
- Recommended next step: keep ping in the diagnostics toolchain without treating
  it as proof of higher-level Filecoin support.

Filecoin request/response protocols
-----------------------------------

Upstream references for this section:

- `Lotus hello service implementation <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/hello/hello.go>`_
- `Forest hello request/response behavior <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/hello/behaviour.rs>`_
- `Forest hello wire types <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/hello/message.rs>`_
- `Lotus chain exchange protocol and client/server paths <https://github.com/filecoin-project/lotus/blob/v1.35.0/chain/exchange/protocol.go>`_
- `Lotus chain exchange server behavior <https://github.com/filecoin-project/lotus/blob/v1.35.0/chain/exchange/server.go>`_
- `Lotus chain exchange client behavior <https://github.com/filecoin-project/lotus/blob/v1.35.0/chain/exchange/client.go>`_
- `Forest chain exchange wrapper and wire types <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/chain_exchange/mod.rs>`_
- `Forest chain exchange messages <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/chain_exchange/message.rs>`_

Hello protocol ID
~~~~~~~~~~~~~~~~~

- Status: ``implemented``
- Upstream evidence: Lotus and Forest both use ``/fil/hello/1.0.0`` as the
  hello protocol ID.
- py-libp2p evidence: ``libp2p/filecoin/constants.py``.
- Current practical support: the constant is exposed and can be used for peer
  capability checks and protocol-list inspection.
- Missing pieces / failure modes: constant parity alone does not provide the
  Filecoin hello request/response service.
- Recommended next step: keep the constant stable and use it as the anchor for
  future hello behavior work.

Hello runtime / wire behavior
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Status: ``missing``
- Priority: ``P1``
- Upstream evidence: Lotus exchanges a hello tipset/genesis payload and latency
  response over a CBOR request/response stream; Forest wraps the hello
  request/response flow with codec, behavior, and peer management logic.
- py-libp2p evidence: ``libp2p/filecoin/constants.py`` and
  ``examples/filecoin/filecoin_ping_identify_demo.py``.
- Current practical support: ``py-libp2p`` can detect whether a peer advertises
  hello support, but it does not speak the hello wire protocol today.
- Missing pieces / failure modes: no hello request/response codec; no hello
  service behavior or inbound/outbound handshake logic; no genesis/tipset
  validation or latency-response handling.
- Recommended next step: implement a dedicated hello codec plus request/response
  behavior before claiming runtime hello interoperability.

Chain exchange protocol ID
~~~~~~~~~~~~~~~~~~~~~~~~~~

- Status: ``implemented``
- Upstream evidence: Lotus and Forest both use ``/fil/chain/xchg/0.0.1`` for
  chain exchange.
- py-libp2p evidence: ``libp2p/filecoin/constants.py``.
- Current practical support: the constant is exposed for diagnostics and
  protocol-list inspection.
- Missing pieces / failure modes: the constant does not provide chain exchange
  request/response support on its own.
- Recommended next step: keep the protocol ID stable and track runtime parity
  separately.

Chain exchange request/response behavior
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Status: ``missing``
- Priority: ``P1``
- Upstream evidence: Lotus validates chain exchange requests, serves compacted
  tipset/message responses, and performs client-side response validation;
  Forest defines typed request/response messages, request-response behavior, and
  provider logic for compacted messages.
- py-libp2p evidence: ``libp2p/filecoin/constants.py`` and
  ``examples/filecoin/filecoin_ping_identify_demo.py``.
- Current practical support: ``py-libp2p`` can confirm that a peer advertises
  chain exchange, but it does not implement the typed request/response behavior.
- Missing pieces / failure modes: no chain exchange request/response codec; no
  typed request/response message models; no server/provider path or client-side
  validation path.
- Recommended next step: treat full chain exchange as a dedicated follow-up
  module, not as a docs-only claim.

Filecoin pubsub compatibility
-----------------------------

Upstream references for this section:

- `Lotus Filecoin pubsub defaults and scoring <https://github.com/filecoin-project/lotus/blob/v1.35.0/node/modules/lp2p/pubsub.go>`_
- `Lotus Filecoin topic and DHT helpers <https://github.com/filecoin-project/lotus/blob/v1.35.0/build/params_shared_funcs.go>`_
- `Forest gossipsub behavior construction <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/behaviour.rs>`_
- `Forest score thresholds and topic-score references <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/gossip_params.rs>`_
- `Forest topic subscription behavior <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/service.rs>`_

Gossipsub protocol negotiation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Status: ``implemented``
- Upstream evidence: Filecoin nodes negotiate gossipsub across the
  ``/meshsub/2.0.0``, ``/meshsub/1.2.0``, ``/meshsub/1.1.0``, and
  ``/meshsub/1.0.0`` family.
- py-libp2p evidence: ``libp2p/filecoin/pubsub.py`` and
  ``examples/filecoin/filecoin_pubsub_demo.py``.
- Current practical support: ``build_filecoin_gossipsub()`` exposes the
  Filecoin-oriented protocol set, and the observer demo reports the selected
  protocol IDs in its snapshot.
- Missing pieces / failure modes: negotiation parity does not imply full
  scoring, gating, or allowlist parity.
- Recommended next step: keep the negotiation set stable and use the rows below
  to track the deeper behavior gaps.

Filecoin topic naming
~~~~~~~~~~~~~~~~~~~~~

- Status: ``implemented``
- Upstream evidence: Lotus derives ``/fil/blocks/<network>``,
  ``/fil/msgs/<network>``, and ``/fil/kad/<network>`` from shared helper
  functions; Forest subscribes to the Filecoin block/message topics with the
  network name suffix.
- py-libp2p evidence: ``libp2p/filecoin/constants.py``,
  ``libp2p/filecoin/networks.py``, and ``libp2p/filecoin/cli.py``.
- Current practical support: ``py-libp2p`` exposes reusable topic/DHT helpers
  and the correct alias-to-genesis-network mapping for mainnet and calibnet.
- Missing pieces / failure modes: none for the helper layer; this is one of the
  fully shipped Module 5 pieces.
- Recommended next step: keep the helpers pinned to upstream snapshots and
  update them only when upstream changes are explicitly reviewed.

Filecoin message ID function
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Status: ``implemented``
- Upstream evidence: Lotus hashes pubsub payload bytes with Blake2b for the
  Filecoin message ID; Forest configures gossipsub message IDs from
  Blake2b-256 over message data.
- py-libp2p evidence: ``libp2p/filecoin/constants.py`` and
  ``libp2p/filecoin/pubsub.py``.
- Current practical support: ``filecoin_message_id()`` provides the expected
  ``blake2b-256(data)`` strategy and the pubsub preset installs it by default.
- Missing pieces / failure modes: message ID parity does not validate Filecoin
  block/message semantics.
- Recommended next step: keep this stable as the message identity anchor for
  the observer/preset workflow.

Score thresholds
~~~~~~~~~~~~~~~~

- Status: ``implemented``
- Upstream evidence: Lotus and Forest both expose the same peer-score threshold
  set for gossip, publish, graylist, accept-PX, and opportunistic grafting.
- py-libp2p evidence: ``libp2p/filecoin/constants.py``,
  ``libp2p/filecoin/pubsub.py``, and ``libp2p/filecoin/cli.py``.
- Current practical support: ``build_filecoin_score_params()`` and
  ``filecoin-dx preset`` report the threshold values used by the current
  Filecoin DX layer.
- Missing pieces / failure modes: threshold parity alone does not deliver the
  richer upstream per-topic score behavior.
- Recommended next step: keep using ``filecoin-dx preset`` as the authoritative
  runtime preset dump.

Full topic scoring parity
~~~~~~~~~~~~~~~~~~~~~~~~~

- Status: ``partial``
- Priority: ``P2``
- Upstream evidence: Lotus configures topic scoring, peer gater, allowlist
  filtering, and bootstrapper-specific behavior around block/message/drand
  topics; Forest carries topic-score parameters for block/message topics but
  does not mirror Lotus knob-for-knob either.
- py-libp2p evidence: ``libp2p/filecoin/pubsub.py`` and
  ``examples/filecoin/filecoin_pubsub_demo.py``.
- Current practical support: ``py-libp2p`` implements the Filecoin threshold
  values and stores a curated reference copy of the upstream topic-score
  constants.
- Missing pieces / failure modes: no peer gater; no subscription allowlist
  parity; no runtime use of the full topic-score reference values.
- Recommended next step: expand the pubsub preset only when the project is
  ready to own the extra behavioral surface and tests that come with it.

Bootstrapper / PX / direct-peer behavior
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Status: ``partial``
- Priority: ``P2``
- Upstream evidence: Lotus changes mesh/PX behavior for bootstrappers and
  supports direct-peer configuration; Forest maintains bootstrap peer redial
  behavior at the service layer.
- py-libp2p evidence: ``libp2p/filecoin/pubsub.py`` and
  ``libp2p/filecoin/bootstrap.py``.
- Current practical support: ``py-libp2p`` can build bootstrapper-flavored
  gossipsub presets, expose PX toggles, and accept explicit direct peers.
- Missing pieces / failure modes: no peer-gater parity; no Lotus-style
  subscription allowlist; no full bootstrapper-service semantics beyond runtime
  bootstrap address helpers.
- Recommended next step: treat bootstrapper and direct-peer tuning as a
  second-stage pubsub parity effort rather than broadening the default Module 2
  surface.

Drand / F3 topic handling
~~~~~~~~~~~~~~~~~~~~~~~~~

- Status: ``missing``
- Priority: ``P3``
- Upstream evidence: Lotus attaches drand topics and optional F3 topics to its
  pubsub allowlist; the Forest corpus provided here focuses on Filecoin
  block/message topics.
- py-libp2p evidence: ``libp2p/filecoin/pubsub.py`` and
  ``examples/filecoin/filecoin_pubsub_demo.py``.
- Current practical support: the current DX layer is intentionally limited to
  Filecoin block/message topics and records drand values only as reference
  data.
- Missing pieces / failure modes: no drand topic construction/runtime
  subscription path; no F3 topic support; no allowlist or validator integration
  for those adjacent topics.
- Recommended next step: keep drand/F3 work as a later expansion once the core
  Filecoin block/message surface is stable.

Out-of-scope note
-----------------

Upstream references for this section:

- `Forest service includes Bitswap alongside the Filecoin-specific protocols <https://github.com/ChainSafe/forest/blob/v0.32.2/src/libp2p/service.rs>`_
- `py-libp2p ships generic bitswap examples separately from the Filecoin DX layer <https://py-libp2p.readthedocs.io/en/stable/examples.bitswap.html>`_

Bitswap note
~~~~~~~~~~~~

- Status: ``out_of_scope``
- Upstream evidence: Forest includes bitswap in its broader libp2p service, but
  bitswap is not a Filecoin-specific DX surface in this module.
- py-libp2p evidence: ``docs/filecoin_architecture_positioning.rst``.
- Current practical support: Module 2 does not make Filecoin-specific bitswap
  claims; it stays focused on protocol support mapping for hello, chain
  exchange, and pubsub compatibility.
- Missing pieces / failure modes: none for Module 2, because the protocol is
  explicitly scoped out here.
- Recommended next step: track Filecoin-specific bitswap questions in a separate
  interoperability or performance module if they become necessary.

Roadmap priorities
------------------

- ``P1``: implement hello request/response wire behavior with typed messages and
  a request-response service; implement chain exchange request/response behavior
  with typed messages and response validation.
- ``P2``: add richer gossipsub scoring, gating, allowlist, and bootstrapper
  parity.
- ``P3``: add drand/F3 topic expansion and adjacent pubsub surfaces after the
  core Filecoin block/message workflow is stable.
