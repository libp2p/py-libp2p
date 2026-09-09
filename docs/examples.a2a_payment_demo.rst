A2A Payment Demo
================

This example demonstrates an A2A-shaped Filecoin payment and storage workflow
built on top of the high-level libp2p request/response helper.

It keeps the transport fully inside py-libp2p but models a custom binding that
resembles the A2A JSON-RPC task flow:

- fetch an Agent Card-like capability document
- send a ``SendMessage`` request that creates a task
- receive ``TASK_STATE_AUTH_REQUIRED`` with a Filecoin Pay-style quote
- send a follow-up authorization message for the same task
- fetch the completed task with payment and storage artifacts

By default this transport-focused example remains local and uses the simulated
execution backend. For the official A2A HTTP/JSON-RPC + SSE facade and the
optional Synapse-backed execution path, see :doc:`examples.a2a_http_payment_demo`.

.. code-block:: console

    $ a2a-payment-demo
    Listener ready, listening on:
    ...

Copy the printed command into another terminal, for example:

.. code-block:: console

    $ a2a-payment-demo -d /ip4/127.0.0.1/tcp/8000/p2p/<PEER_ID> --name hello.txt --size 256
    Agent Card:
    ...
    Task after initial SendMessage:
    ...
    Task after payment authorization:
    ...

To demonstrate partial provider fulfilment while still completing the task:

.. code-block:: console

    $ a2a-payment-demo -d /ip4/127.0.0.1/tcp/8000/p2p/<PEER_ID> --name hello.txt --size 256 --copies 3

The full source code for this example is below:

.. literalinclude:: ../examples/request_response/a2a_payment_demo.py
    :language: python
    :linenos:
