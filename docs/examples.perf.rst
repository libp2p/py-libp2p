Perf Protocol Demo
==================

This example demonstrates how to use the libp2p ``perf`` protocol to measure
transfer performance between two nodes.

The perf protocol sends and receives data to measure throughput, reporting
both intermediary progress and final results.

Running the Example
-------------------

First, start the server in one terminal:

.. code-block:: console

    $ python examples/perf/perf_example.py -p 8000

    Perf server ready, listening on:
      /ip4/127.0.0.1/tcp/8000/p2p/QmXfptdHU6hqG95JswxYVUH4bphcK8y18mhFcgUQFe6fCN

    Protocol: /perf/1.0.0

    Run client with:
      python perf_example.py -d /ip4/127.0.0.1/tcp/8000/p2p/QmXfptdHU6hqG95JswxYVUH4bphcK8y18mhFcgUQFe6fCN

    Waiting for incoming perf requests...

Then, in another terminal, run the client with the multiaddr from the server:

.. code-block:: console

    $ python examples/perf/perf_example.py -d /ip4/127.0.0.1/tcp/8000/p2p/QmXfptdHU6hqG95JswxYVUH4bphcK8y18mhFcgUQFe6fCN

    Connecting to QmXfptdHU6hqG95JswxYVUH4bphcK8y18mhFcgUQFe6fCN...
    Connected!

    Measuring performance:
      Upload:   2560 bytes
      Download: 2560 bytes

      Uploading: 2560 bytes in 0.01s (256000 bytes/s)
      Downloading: 2560 bytes in 0.01s (256000 bytes/s)

    ==================================================
    Performance Results:
      Total time:     0.025 seconds
      Uploaded:       2560 bytes
      Downloaded:     2560 bytes
      Total data:     5120 bytes
      Throughput:     204800 bytes/s
    ==================================================

Command Line Options
--------------------

.. code-block:: text

    -p, --port          Listening port (default: random free port)
    -d, --destination   Destination multiaddr (if not set, runs as server)
    -u, --upload        Upload size in units of 256 bytes (default: 10)
    -D, --download      Download size in units of 256 bytes (default: 10)

Source Code
-----------

.. literalinclude:: ../examples/perf/perf_example.py
    :language: python
    :linenos:
