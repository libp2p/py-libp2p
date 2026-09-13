Gossipsub Versioned Examples
============================

These examples demonstrate GossipSub protocol evolution in py-libp2p, from
basic mesh pubsub through experimental profiles.

Runnable scripts live under ``examples/pubsub/gossipsub/``. For a broader
narrative and feature matrix, see GitHub Discussion
`#1297 <https://github.com/libp2p/py-libp2p/discussions/1297>`_.
The classic interactive chat demo remains documented in
:doc:`examples.pubsub`.

.. note::

   Upstream libp2p currently standardizes GossipSub through v1.3.
   ``/meshsub/1.4.0`` and ``/meshsub/2.0.0`` are **experimental py-libp2p
   profiles**. Cross-implementation interoperability should not be assumed
   without explicit interop testing.

Quick start
-----------

Run each command from the repository root:

.. code-block:: console

    $ python examples/pubsub/gossipsub/gossipsub_v1.0.py --nodes 5 --duration 30
    $ python examples/pubsub/gossipsub/gossipsub_v1.1.py --nodes 5 --duration 30
    $ python examples/pubsub/gossipsub/gossipsub_v1.2.py --nodes 5 --duration 30
    $ python examples/pubsub/gossipsub/gossipsub_v1.3.py --nodes 6 --duration 40
    $ python examples/pubsub/gossipsub/gossipsub_v1.4.py --nodes 6 --duration 40
    $ python examples/pubsub/gossipsub/gossipsub_v2.0.py --nodes 5 --duration 30
    $ python examples/pubsub/gossipsub/compare_versions.py --nodes 4 --duration 8

Use ``--verbose`` for debug logs. Prefer short ``--duration`` values while
developing.

What each script shows
----------------------

* **v1.0** — mesh pubsub and **fanout** (``node_0`` publishes without
  subscribing).
* **v1.1** — peer scoring (P1–P7), prune backoff, peer exchange (PX), and a
  role-based application score (P6). Prints a score snapshot at the end.
* **v1.2** — IDONTWANT filtering on top of scoring.
* **v1.3** — Extensions Control Message and Topic Observation
  (observer / UNOBSERVE lifecycle).
* **v1.4** *(experimental)* — rate limits, adaptive gossip, spam burst demo.
* **v2.0** *(experimental)* — spam/eclipse protection flags, topic validator
  rejecting ``invalid_*`` payloads, periodic peer score dumps.
* **compare_versions.py** — side-by-side metrics for ``normal`` / ``spam`` /
  ``churn`` scenarios (optional ``--json``).

Shared helpers
--------------

Boilerplate (host lifecycle, ring+chord wiring, trio deadlines) lives in
``examples/pubsub/gossipsub/_common.py``. Version scripts keep protocol
configuration and feature checklists so newcomers can still read one file for
the educational point of that release.

Related docs
------------

* :doc:`examples.pubsub` — PubSub chat example
* :doc:`gossipsub-1.2` — GossipSub 1.2 notes
* :doc:`gossipsub-1.3` — GossipSub 1.3 extensions and Topic Observation
* `Discussion #1297 <https://github.com/libp2p/py-libp2p/discussions/1297>`_
