Identify Demo
=============

This example demonstrates the libp2p identify protocol, which allows peers to exchange information about each other.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ python identify.py
    First host listening. Run this from another console:

    python identify.py -p 8889 -d /ip4/0.0.0.0/tcp/8888/p2p/QmUe4tNG9naN6zxaQRhawehA5NvBPGJifRbL5xrj4wEwvG

    Waiting for incoming identify request...


Copy the line that starts with ``python identify.py -p 8889``, open a new terminal and paste it in
.. code-block:: console

    $ python identify.py -p 8889 -d /ip4/0.0.0.0/tcp/8888/p2p/QmUe4tNG9naN6zxaQRhawehA5NvBPGJifRbL5xrj4wEwvG
    dialer (host_b) listening on /ip4/0.0.0.0/tcp/8889
    Second host connecting to peer: QmUe4tNG9naN6zxaQRhawehA5NvBPGJifRbL5xrj4wEwvG
    Starting identify protocol...
    Identify response:
    Public Key (Base64): CAASpgIwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQC298b/biPYaa0P14oZKKNem8gbG6gYkM153K9JVXHPACOGAYqMHrJ5ET2PzfK6H2187nuGC/91fKoBBHJx68KPewpgWbpYXGn3JFnTVJ2+Dufut3pCk2GrbFaAcWdf9pLcPOpwNGUI17lQN67yStsOa7P1GOW4oWYdRU9LzLOyHpC82Ag5J6T0lmjHAaGLEeVhum8gOq1xZC4o2KnHboXxTeHkVvfNteGaYeWcm+ZPKLeiBRWK9ud247k5J6jIrL0SYgpsjpIz2BlANr08H7BTgFkXrb01qmJtuHlr/F4+s0k9YHqH67yvbCHrFSz4CtgXR9fozJ80v7wbBtXMNMmZAgMBAAE=
    Listen Addresses: ['/ip4/0.0.0.0/tcp/8888/p2p/QmUe4tNG9naN6zxaQRhawehA5NvBPGJifRbL5xrj4wEwvG']
    Protocols: ['/ipfs/id/1.0.0', '/ipfs/ping/1.0.0']
    Observed Address: ['/ip4/127.0.0.1/tcp/35934']
    Protocol Version: ipfs/0.1.0
    Agent Version: py-libp2p/0.2.0


The first host acts as a listener that waits for incoming identify requests. The second host connects to the first one and sends an identify request. The response contains information about the first host, including its public key, listen addresses, supported protocols, and the address through which it observed the second host.

The full source code for this example is below:

.. literalinclude:: ../examples/identify/identify.py
    :language: python
    :linenos:
