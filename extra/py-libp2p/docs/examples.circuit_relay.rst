Circuit Relay v2 Example
========================

This example demonstrates how to use Circuit Relay v2 in py-libp2p.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ circuit-relay-demo --role relay --port 8000 --seed 1
    Starting relay node...
    Listening on: /ip4/0.0.0.0/tcp/8000/p2p/16Uiu2HAm765pEhEgJJmz5xHLt8Ay2a16qtS9uPzjUGjuCKTAtQYN

Copy the relay-id after from the line ``Listening on:``,
open a new terminal in same folder and enter below commands

.. code-block:: console

    $ circuit-relay-demo --role destination --port 8001 --seed 2 --relay-addr 16Uiu2HAm765pEhEgJJmz5xHLt8Ay2a16qtS9uPzjUGjuCKTAtQYN
    Starting destination node...
    Listening on: /ip4/0.0.0.0/tcp/8001/p2p/16Uiu2HAkyfVeK1wARrrgCUkEfohLpDcW34TkXc7r426vGcRhy3h2

    # Post connection and message transfer
    Received message (65 bytes): Hello from 16Uiu2HAkyadSbNMy8BuAQLHeyp71kt4CNaUUKUhERB83NsjKTGAb!
    Sent response to 16Uiu2HAkyadSbNMy8BuAQLHeyp71kt4CNaUUKUhERB83NsjKTGAb

Copy the destination-id after from the line ``Listening on:``,
open a new terminal in same folder and enter below commands

.. code-block:: console

    $ circuit-relay-demo --role source --port 8002 --seed 3 --relay-addr 16Uiu2HAm765pEhEgJJmz5xHLt8Ay2a16qtS9uPzjUGjuCKTAtQYN --dest-id 16Uiu2HAkyfVeK1wARrrgCUkEfohLpDcW34TkXc7r426vGcRhy3h2
    Starting source node...
    Listening on: /ip4/0.0.0.0/tcp/36345/p2p/16Uiu2HAkyadSbNMy8BuAQLHeyp71kt4CNaUUKUhERB83NsjKTGAb

    # Post connection and message transfer
    Connected to relay 16Uiu2HAm765pEhEgJJmz5xHLt8Ay2a16qtS9uPzjUGjuCKTAtQYN
    Successfully connected to destination through relay!
    Sent message to destination
    Received response: Hello! This is 16Uiu2HAkyadSbNMy8BuAQLHeyp71kt4CNaUUKUhERB83NsjKTGAb
    Source operation completed

.. literalinclude:: ../examples/circuit_relay/relay_example.py
    :language: python
    :linenos:
