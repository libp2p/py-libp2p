Request/Response Demo
=====================

This example demonstrates the high-level libp2p request/response helper using a
single JSON request and response over a dedicated protocol stream.

.. code-block:: console

    $ request-response-demo
    Listener ready, listening on:
    ...

Copy the printed command into another terminal, for example:

.. code-block:: console

    $ request-response-demo -d /ip4/127.0.0.1/tcp/8000/p2p/<PEER_ID> --message hello
    Sent: hello
    Received: {'message': 'hello', 'echo': 'HELLO', 'peer': '<PEER_ID>'}

The full source code for this example is below:

.. literalinclude:: ../examples/request_response/request_response_demo.py
    :language: python
    :linenos:
