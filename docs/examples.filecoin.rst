Filecoin DX Examples
====================

Read this first:

- :doc:`filecoin_architecture_positioning`
- :doc:`filecoin_network_parity_and_interop`

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

This observer does not publish messages. It subscribes to Filecoin gossip
topics and reports inbound metadata.

.. code-block:: console

    $ filecoin-pubsub-demo --network mainnet --topic both --seconds 20

.. code-block:: console

    $ filecoin-pubsub-demo --network calibnet --topic blocks --max-messages 25 --json

.. literalinclude:: ../examples/filecoin/filecoin_pubsub_demo.py
    :language: python
    :linenos:

CLI helpers
-----------

.. code-block:: console

    $ filecoin-dx topics --network mainnet --json
    $ filecoin-dx bootstrap --network mainnet --runtime --resolve-dns --json
    $ python -m libp2p.filecoin preset --network calibnet --json
