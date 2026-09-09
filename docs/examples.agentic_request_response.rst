Agentic Request/Response Demo
=============================

This example demonstrates a Filecoin-aligned, locally simulated agent control
workflow built on top of the high-level libp2p request/response helper.

It performs two one-shot exchanges over fresh protocol streams:

- a ``capability_query`` to discover the agent's supported task semantics
- a ``store_intent`` request that returns a simulated storage result

The example does not call Filecoin services, Synapse SDK, or external providers.
It models only the control-plane messages and result semantics.

.. code-block:: console

    $ agentic-request-response-demo
    Listener ready, listening on:
    ...

Copy the printed command into another terminal, for example:

.. code-block:: console

    $ agentic-request-response-demo -d /ip4/127.0.0.1/tcp/8000/p2p/<PEER_ID> --name hello.txt --size 256
    Capability response:
    ...
    Store result summary:
      status: complete
      ...

To demonstrate partial success with an unhealthy secondary provider:

.. code-block:: console

    $ agentic-request-response-demo -d /ip4/127.0.0.1/tcp/8000/p2p/<PEER_ID> --name hello.txt --size 256 --copies 3

The full source code for this example is below:

.. literalinclude:: ../examples/request_response/agentic_request_response_demo.py
    :language: python
    :linenos:
