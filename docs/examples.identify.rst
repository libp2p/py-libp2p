Identify Protocol Demo
======================

This example demonstrates how to use the libp2p ``identify`` protocol.

.. code-block:: console

    $ python -m pip install libp2p
    Collecting libp2p
    ...
    Successfully installed libp2p-x.x.x
    $ identify-demo
    First host listening. Run this from another console:

    identify-demo -p 8889 -d /ip4/0.0.0.0/tcp/8888/p2p/QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM

    Waiting for incoming identify request...

Copy the line that starts with ``identify-demo -p 8889 ....``, open a new terminal in the same
folder and paste it in:

.. code-block:: console

    $ identify-demo -p 8889 -d /ip4/0.0.0.0/tcp/8888/p2p/QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM
    dialer (host_b) listening on /ip4/0.0.0.0/tcp/8889
    Second host connecting to peer: QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM
    Starting identify protocol...
    Identify response:
    Public Key (Base64): CAASpgIwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDC6c/oNPP9X13NDQ3Xrlp3zOj+ErXIWb/A4JGwWchiDBwMhMslEX3ct8CqI0BqUYKuwdFjowqqopOJ3cS2MlqtGaiP6Dg9bvGqSDoD37BpNaRVNcebRxtB0nam9SQy3PYLbHAmz0vR4ToSiL9OLRORnGOxCtHBuR8ZZ5vS0JEni8eQMpNa7IuXwyStnuty/QjugOZudBNgYSr8+9gH722KTjput5IRL7BrpIdd4HNXGVRm4b9BjNowvHu404x3a/ifeNblpy/FbYyFJEW0looygKF7hpRHhRbRKIDZt2BqOfT1sFkbqsHE85oY859+VMzP61YELgvGwai2r7KcjkW/AgMBAAE=
    Listen Addresses: ['/ip4/0.0.0.0/tcp/8888/p2p/QmUiN4R3fNrCoQugGgmmb3v35neMEjKFNrsbNGVDsRHWpM']
    Protocols: ['/ipfs/id/1.0.0', '/ipfs/ping/1.0.0']
    Observed Address: ['/ip4/127.0.0.1/tcp/38082']
    Protocol Version: ipfs/0.1.0
    Agent Version: py-libp2p/0.2.0


The full source code for this example is below:

.. literalinclude:: ../examples/identify/identify.py
    :language: python
    :linenos:
