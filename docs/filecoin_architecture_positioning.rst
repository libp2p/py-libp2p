Filecoin Architecture Positioning for py-libp2p
===============================================

This page positions ``py-libp2p`` within the Filecoin ecosystem so developers
can choose the right stack for the right job.

How py-libp2p fits in Filecoin architecture today
-------------------------------------------------

``py-libp2p`` is a Python networking toolkit that can interoperate at the
libp2p layer, and this package provides a Filecoin-focused DX layer for protocol
IDs, topic formats, bootstrap presets, and practical examples.

Normative references:

- `Filecoin Network Interface <https://spec.filecoin.io/systems/filecoin_nodes/network/>`_
- `Lotus reference implementation <https://github.com/filecoin-project/lotus>`_
- `Forest implementation <https://github.com/ChainSafe/forest>`_

Where py-libp2p is production-viable today
------------------------------------------

``py-libp2p`` is production-viable for focused networking tasks that do not
require full Filecoin consensus execution:

- protocol/tooling adapters around known Filecoin protocol IDs and topics.
- telemetry and observer workflows (for example read-only pubsub observers).
- integration harnesses and dev/testnet experimentation.
- controlled research and replay tooling where Python ergonomics are preferred.

Normative references:

- `py-libp2p project repository <https://github.com/libp2p/py-libp2p>`_
- `py-libp2p bootstrap discovery docs <https://py-libp2p.readthedocs.io/en/latest/libp2p.discovery.bootstrap.html>`_

Where Lotus/Forest (full implementations) are still required
-------------------------------------------------------------

Lotus/Forest remain required for full node behavior tied to Filecoin chain
consensus and state transitions. Examples include:

- canonical chain sync and finality handling.
- actor/state execution and state-root correctness.
- full message pool policy and block production integration.
- complete protocol-surface parity expected from production validators/miners.

Normative references:

- `Filecoin ChainSync spec <https://spec.filecoin.io/systems/filecoin_blockchain/chainsync/>`_
- `Filecoin node types <https://spec.filecoin.io/systems/filecoin_nodes/node_types/>`_
- `Lotus node use-cases docs <https://lotus.filecoin.io/lotus/get-started/use-cases/>`_

Suggested use cases: tooling, analytics, testnets, research
------------------------------------------------------------

Recommended use-cases for ``py-libp2p`` + ``libp2p.filecoin``:

- Tooling: protocol/topic inspectors, peer capability checks, and bootstrap
  diagnostics.
- Analytics: read-only subscription pipelines and metadata capture.
- Testnets: rapid prototyping of network behaviors and failure experiments.
- Research: hypothesis testing for scoring, peer selection, and transport
  adaptation before upstreaming to larger clients.

Normative references:

- `py-libp2p bitswap example docs <https://py-libp2p.readthedocs.io/en/stable/examples.bitswap.html>`_
- `Lotus bootstrap configuration docs <https://lotus.filecoin.io/lotus/configure/bootstrap/>`_

Decision boundaries and anti-goals
----------------------------------

This package is intentionally DX/tooling scoped.

Out of scope:

- replacing Lotus/Forest as full production nodes.
- implementing full chain-sync/state-validation pipeline in Python.
- claiming consensus-equivalent behavior from helper constants alone.

In scope:

- accurate Filecoin networking constants and presets.
- practical developer-facing examples for connect, ping/identify, and read-only
  pubsub observation.
- explicit traceability back to pinned Lotus ``v1.35.0`` and Forest ``0.32.2``
  references.

Normative references:

- `Filecoin implementations overview <https://docs.filecoin.io/nodes/implementations>`_
- `Filecoin protocol repository <https://github.com/filecoin-project/filecoin-specs>`_

Capability matrix
-----------------

.. list-table::
   :header-rows: 1

   * - Concern
     - py-libp2p status
     - Lotus/Forest requirement
     - Why
     - Recommended path
   * - Filecoin protocol/topic constants
     - Implemented in ``libp2p.filecoin``
     - Not required for constants themselves
     - Values are pinned from upstream snapshots
     - Use DX helpers directly
   * - Bootstrap address handling
     - Implemented (canonical + runtime helpers)
     - Not required for helper usage
     - DNS-first canonical lists need runtime adaptation in Python workflows
     - Use ``get_runtime_bootstrap_addresses``
   * - Read-only gossip observation
     - Implemented
     - Not required
     - Observer workflows do not require consensus execution
     - Use ``filecoin-pubsub-demo`` observer mode
   * - Peer diagnostics (connect/ping/identify)
     - Implemented as examples
     - Not required
     - Useful for interoperability checks and network diagnostics
     - Use ``filecoin-connect-demo`` and ``filecoin-ping-identify-demo``
   * - Full chain sync + state execution
     - Not implemented
     - Required
     - Requires full protocol semantics and actor/state machinery
     - Run Lotus or Forest nodes

DHT format divergence note
--------------------------

There is an explicit divergence between commonly cited textual spec form and
the pinned Lotus helper snapshot used in this implementation:

- Textual form often cited: ``fil/<network-name>/kad/1.0.0``.
- Pinned Lotus helper form: ``/fil/kad/<network-name>``.

Implementation decision:

- default to pinned implementation parity for ``dht_protocol_name`` in
  ``libp2p.filecoin``, and document the divergence explicitly.

Rationale:

- this implementation is parity-driven against the Lotus ``v1.35.0`` and Forest
  ``0.32.2`` code snapshots provided for implementation review.
