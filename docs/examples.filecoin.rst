Filecoin DX Examples
====================

Read this first:

- :doc:`filecoin_architecture_positioning`
- :doc:`filecoin_protocol_support_matrix`

These examples show practical Filecoin-focused workflows using
``libp2p.filecoin``.

Connect to a Filecoin peer
--------------------------

.. code-block:: console

    $ filecoin-connect-demo --network mainnet --resolve-dns --json

.. literalinclude:: ../examples/filecoin/filecoin_connect_demo.py
    :language: python
    :linenos:

Ping + identify a Filecoin peer
-------------------------------

.. code-block:: console

    $ filecoin-ping-identify-demo --network calibnet --ping-count 3 --json

.. literalinclude:: ../examples/filecoin/filecoin_ping_identify_demo.py
    :language: python
    :linenos:

Read-only pubsub observer
-------------------------

This observer is the Filecoin-compatible gossipsub reference example for the
current DX layer. It does not publish messages, subscribes to Filecoin gossip
topics, and reports inbound metadata plus the exact compatibility snapshot it is
running with.

Current limitations:

- no full topic-scoring parity
- no peer gater or subscription allowlist parity
- no drand/F3 topic support
- no publish path
- no block/message semantic validation beyond observation

.. code-block:: console

    $ filecoin-pubsub-demo --network mainnet --topic both --seconds 20

.. code-block:: console

    $ filecoin-pubsub-demo --network calibnet --topic blocks --max-messages 25 --json

.. literalinclude:: ../examples/filecoin/filecoin_pubsub_demo.py
    :language: python
    :linenos:

Use ``filecoin-dx preset --json`` when you need the authoritative runtime preset
dump that the current example is derived from.

CLI helpers
-----------

.. code-block:: console

    $ filecoin-dx topics --network mainnet --json
    $ filecoin-dx bootstrap --network mainnet --runtime --resolve-dns --json
    $ python -m libp2p.filecoin preset --network calibnet --json
