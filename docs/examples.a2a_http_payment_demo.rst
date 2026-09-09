A2A HTTP Payment Demo
=====================

This example exposes the payment demo through the official A2A Python SDK over
HTTP JSON-RPC with Server-Sent Events (SSE) for streaming updates.

It keeps the same task semantics as the libp2p demo while adding a standards-
facing surface:

- ``GET /.well-known/agent-card.json`` for discovery
- ``POST /rpc`` with ``SendMessage`` / ``GetTask`` / ``CancelTask`` / ``ListTasks``
- ``SendStreamingMessage`` over SSE for real-time task progress and artifact updates

The HTTP facade can run in two backend modes:

- ``simulation``: safe local mode, no external services required
- ``synapse``: real Synapse/Filecoin execution through a Node sidecar

Python requirements
-------------------

Install the optional Python packages needed for the HTTP facade:

.. code-block:: console

    $ pip install "a2a-sdk[http-server]" uvicorn

Node sidecar requirements
-------------------------

Install the sidecar dependencies once:

.. code-block:: console

    $ cd examples/request_response/synapse_sidecar
    $ npm install

Simulation mode
---------------

Run the official A2A server locally in simulation mode:

.. code-block:: console

    $ a2a-http-payment-demo --backend simulation --host 127.0.0.1 --port 9999

The Agent Card will advertise ``http://127.0.0.1:9999/rpc`` as the preferred
JSON-RPC interface.

Synapse-backed mode
-------------------

To enable real Synapse/Filecoin execution, configure a funded testnet wallet
and run the server with the Synapse backend:

.. code-block:: console

    $ export A2A_SYNAPSE_PRIVATE_KEY=0x...
    $ export A2A_SYNAPSE_NETWORK=calibration
    $ export A2A_SYNAPSE_EXECUTE_TRANSACTIONS=1
    $ a2a-http-payment-demo --backend synapse --host 127.0.0.1 --port 9999

Important environment variables:

- ``A2A_SYNAPSE_PRIVATE_KEY``: private key used by the Node sidecar
- ``A2A_SYNAPSE_NETWORK``: ``calibration`` or ``mainnet`` (default: ``calibration``)
- ``A2A_SYNAPSE_RPC_URL``: optional custom Filecoin RPC endpoint
- ``A2A_SYNAPSE_PANDORA_ADDRESS``: optional Pandora contract override
- ``A2A_SYNAPSE_EXECUTE_TRANSACTIONS``: set to ``1`` to allow real funding and approval transactions
- ``A2A_SYNAPSE_VERIFY_DOWNLOAD``: set to ``0`` to skip retrieval verification

The Synapse bridge is intentionally conservative. If the wallet needs funding or
service approval and ``A2A_SYNAPSE_EXECUTE_TRANSACTIONS`` is not enabled, the
task fails with an explicit instruction instead of spending automatically.

What the real backend adds
--------------------------

When the Synapse backend is enabled, the demo stops being purely simulated:

- the quote path inspects the wallet, payment account, and allowance requirements
- the store path can perform deposit and service-approval transactions
- the storage receipt includes real ``CommP`` / piece identifiers, proof set data,
  provider address, and retrieval verification metadata

The full source code for the HTTP facade is below:

.. literalinclude:: ../examples/request_response/a2a_http_payment_demo.py
    :language: python
    :linenos:
