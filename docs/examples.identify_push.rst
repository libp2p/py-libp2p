Identify Push Protocol Demo
===========================

This example demonstrates how to use the libp2p ``identify-push`` protocol, which allows nodes to proactively push their identity information to peers when it changes.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ identify-push-demo
    ==== Starting Identify-Push Example ====

    Host 1 listening on /ip4/127.0.0.1/tcp/xxxxx/p2p/QmAbCdEfGhIjKlMnOpQrStUvWxYz
    Peer ID: QmAbCdEfGhIjKlMnOpQrStUvWxYz
    Host 2 listening on /ip4/127.0.0.1/tcp/xxxxx/p2p/QmZyXwVuTaBcDeRsSkJpOpWrSt
    Peer ID: QmZyXwVuTaBcDeRsSkJpOpWrSt

    Connecting Host 2 to Host 1...
    Host 2 successfully connected to Host 1

    Host 1 pushing identify information to Host 2...
    Identify push completed successfully!

    Example completed successfully!

There is also a more interactive version of the example which runs as separate listener and dialer processes:

.. code-block:: console

    $ identify-push-listener-dialer-demo

    ==== Starting Identify-Push Listener on port 8888 ====

    Listener host ready!
    Listening on: /ip4/0.0.0.0/tcp/8888/p2p/QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM
    Peer ID: QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM

    Run dialer with command:
    identify-push-listener-dialer-demo -d /ip4/0.0.0.0/tcp/8888/p2p/QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM

    Waiting for incoming connections... (Ctrl+C to exit)

Copy the line that starts with ``identify-push-listener-dialer-demo -d ...``, open a new terminal in the same
folder and paste it in:

.. code-block:: console

    $ identify-push-listener-dialer-demo -d /ip4/0.0.0.0/tcp/8888/p2p/QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM

    ==== Starting Identify-Push Dialer on port 8889 ====

    Dialer host ready!
    Listening on: /ip4/0.0.0.0/tcp/8889/p2p/QmZyXwVuTaBcDeRsSkJpOpWrSt

    Connecting to peer: QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM
    Successfully connected to listener!

    Pushing identify information to listener...
    Identify push completed successfully!

    Example completed successfully!

The identify-push protocol enables libp2p nodes to proactively notify their peers when their metadata changes, such as supported protocols or listening addresses. This helps maintain an up-to-date view of the network without requiring regular polling.

The full source code for these examples is below:

Basic example:

.. literalinclude:: ../examples/identify_push/identify_push_demo.py
    :language: python
    :linenos:

Listener/Dialer example:

.. literalinclude:: ../examples/identify_push/identify_push_listener_dialer.py
    :language: python
    :linenos:
