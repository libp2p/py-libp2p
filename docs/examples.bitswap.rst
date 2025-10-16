Bitswap Example
===============

This example demonstrates the Bitswap protocol for content discovery and file sharing.

Overview
--------

Bitswap is a message-based protocol for exchanging content-addressed blocks between peers.
This example shows how to:

* Start a provider node that serves blocks
* Start a client node that requests blocks
* Exchange blocks between peers
* Share files using Bitswap

Running the Example
-------------------

Provider Mode
~~~~~~~~~~~~~

Start a provider that serves blocks:

.. code-block:: bash

    python examples/bitswap/bitswap.py --mode provider

Or with a specific file:

.. code-block:: bash

    python examples/bitswap/bitswap.py --mode provider --file myfile.txt

The provider will:

1. Start a Bitswap node
2. Add blocks to its store (from file or example data)
3. Print its multiaddr for clients to connect
4. Serve blocks to requesting peers

Client Mode
~~~~~~~~~~~

Start a client that requests blocks:

.. code-block:: bash

    python examples/bitswap/bitswap.py --mode client --provider /ip4/127.0.0.1/tcp/4001/p2p/QmYourPeerID...

Request specific blocks by CID:

.. code-block:: bash

    python examples/bitswap/bitswap.py --mode client --provider <multiaddr> --blocks abc123def456 789012fedcba

Demo Mode
~~~~~~~~~

Run an automated demonstration:

.. code-block:: bash

    python examples/bitswap/bitswap.py --mode demo

How It Works
------------

Provider Node
~~~~~~~~~~~~~

The provider:

1. Creates a Bitswap client with a block store
2. Adds blocks (either from a file or example data)
3. Listens for incoming wantlist requests from peers
4. Sends blocks to peers that request them

.. code-block:: python

    async def run_provider(port=0, file_path=None):
        host = new_host()
        listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

        async with host.run([listen_addr]), trio.open_nursery() as nursery:
            bitswap = BitswapClient(host)
            bitswap.set_nursery(nursery)
            await bitswap.start()

            # Add blocks to serve
            if file_path:
                # Read and split file into blocks
                with open(file_path, "rb") as f:
                    file_data = f.read()

                block_size = 1024
                for i in range(0, len(file_data), block_size):
                    chunk = file_data[i:i + block_size]
                    cid = compute_cid(chunk)
                    await bitswap.add_block(cid, chunk)

            await trio.sleep_forever()

Client Node
~~~~~~~~~~~

The client:

1. Creates a Bitswap client
2. Connects to a provider node
3. Sends wantlist requests for specific blocks
4. Receives blocks and stores them locally

.. code-block:: python

    async def run_client(provider_addr, block_cids):
        host = new_host()
        provider_info = info_from_p2p_addr(provider_addr)

        async with host.run([listen_addr]), trio.open_nursery() as nursery:
            bitswap = BitswapClient(host)
            bitswap.set_nursery(nursery)
            await bitswap.start()

            # Connect to provider
            await host.connect(provider_info)

            # Request blocks
            for cid_hex in block_cids:
                cid = bytes.fromhex(cid_hex)
                data = await bitswap.get_block(cid, provider_info.peer_id)
                print(f"Received block: {data}")

Block Exchange Process
~~~~~~~~~~~~~~~~~~~~~~

1. **Client wants a block**:

   - Computes or receives the CID (Content Identifier)
   - Checks local block store
   - If not found, adds to wantlist and sends to provider

2. **Provider receives wantlist**:

   - Parses the wantlist message
   - Checks if it has the requested blocks
   - Sends available blocks to the client

3. **Client receives blocks**:

   - Stores blocks in local block store
   - Notifies pending requests
   - Sends cancel messages to other peers

Example Output
--------------

Provider
~~~~~~~~

.. code-block:: text

    2025-10-05 10:00:00 - bitswap_example - INFO - Provider node started with peer ID: QmProviderID...
    2025-10-05 10:00:00 - bitswap_example - INFO - Listening on: /ip4/127.0.0.1/tcp/4001/p2p/QmProviderID...
    2025-10-05 10:00:00 - bitswap_example - INFO - Added block 0: a1b2c3d4... = Hello from Bitswap!
    2025-10-05 10:00:00 - bitswap_example - INFO - Added block 1: e5f6g7h8... = This is block number 2
    2025-10-05 10:00:00 - bitswap_example - INFO - To connect a client, use:
    2025-10-05 10:00:00 - bitswap_example - INFO -   python bitswap.py --mode client --provider /ip4/127.0.0.1/tcp/4001/p2p/QmProviderID...
    2025-10-05 10:00:00 - bitswap_example - INFO - Provider has 4 blocks available

Client
~~~~~~

.. code-block:: text

    2025-10-05 10:01:00 - bitswap_example - INFO - Client node started with peer ID: QmClientID...
    2025-10-05 10:01:00 - bitswap_example - INFO - Connecting to provider QmProviderID...
    2025-10-05 10:01:00 - bitswap_example - INFO - Connected!
    2025-10-05 10:01:00 - bitswap_example - INFO - Requesting block 0: a1b2c3d4...
    2025-10-05 10:01:00 - bitswap_example - INFO - ✓ Received: Hello from Bitswap!
    2025-10-05 10:01:01 - bitswap_example - INFO - Requesting block 1: e5f6g7h8...
    2025-10-05 10:01:01 - bitswap_example - INFO - ✓ Received: This is block number 2
    2025-10-05 10:01:02 - bitswap_example - INFO - Client now has 2 blocks

Features Demonstrated
---------------------

Content-Addressed Storage
~~~~~~~~~~~~~~~~~~~~~~~~~

Blocks are identified by their cryptographic hash (CID):

.. code-block:: python

    def compute_cid(data: bytes) -> bytes:
        return hashlib.sha256(data).digest()

This ensures:

* **Integrity**: Content can be verified by recomputing the hash
* **Deduplication**: Same content has the same CID
* **Immutability**: Content changes result in different CIDs

Wantlist Protocol
~~~~~~~~~~~~~~~~~

Peers communicate what blocks they want:

.. code-block:: python

    # Add to wantlist
    await bitswap.want_block(cid, priority=1)

    # Cancel from wantlist
    await bitswap.cancel_want(cid)

Priority-Based Requests
~~~~~~~~~~~~~~~~~~~~~~~

Blocks can be requested with different priorities:

.. code-block:: python

    await bitswap.want_block(critical_cid, priority=10)  # High
    await bitswap.want_block(normal_cid, priority=1)     # Normal
    await bitswap.want_block(optional_cid, priority=0)   # Low

File Sharing
~~~~~~~~~~~~

Large files are split into blocks for efficient transfer:

.. code-block:: python

    block_size = 1024  # 1KB blocks
    for i in range(0, len(file_data), block_size):
        chunk = file_data[i:i + block_size]
        cid = compute_cid(chunk)
        await bitswap.add_block(cid, chunk)

Code Structure
--------------

The example code is organized as follows:

.. code-block:: text

    examples/bitswap/
    ├── bitswap.py        # Main example script
    ├── README.md         # Example documentation
    └── __init__.py

Key functions:

* ``run_provider(port, file_path)`` - Start a provider node
* ``run_client(provider_addr, block_cids)`` - Start a client node
* ``run_file_transfer_demo()`` - Run automated demo
* ``compute_cid(data)`` - Compute CID for block data

Extending the Example
---------------------

Custom Block Processing
~~~~~~~~~~~~~~~~~~~~~~~

Add custom processing for received blocks:

.. code-block:: python

    class CustomBitswap(BitswapClient):
        async def _process_blocks(self, blocks: list[bytes]) -> None:
            for block_data in blocks:
                # Custom processing
                process_block(block_data)

            # Call parent implementation
            await super()._process_blocks(blocks)

Persistent Storage
~~~~~~~~~~~~~~~~~~

Use a file-based block store:

.. code-block:: python

    from libp2p.bitswap import BlockStore

    class FileBlockStore(BlockStore):
        def __init__(self, base_path):
            self.base_path = Path(base_path)

        async def put_block(self, cid: bytes, data: bytes) -> None:
            file_path = self.base_path / cid.hex()
            file_path.write_bytes(data)

        async def get_block(self, cid: bytes) -> Optional[bytes]:
            file_path = self.base_path / cid.hex()
            return file_path.read_bytes() if file_path.exists() else None

Multiple Providers
~~~~~~~~~~~~~~~~~~

Request blocks from multiple providers:

.. code-block:: python

    async def request_from_multiple(cid, providers):
        async with trio.open_nursery() as nursery:
            results = []

            async def try_provider(provider):
                try:
                    data = await bitswap.get_block(cid, provider)
                    results.append(data)
                    nursery.cancel_scope.cancel()  # Stop others
                except Exception:
                    pass

            for provider in providers:
                nursery.start_soon(try_provider, provider)

        return results[0] if results else None

See Also
--------

* :doc:`libp2p.bitswap` - Bitswap API documentation
* `Bitswap Protocol <https://specs.ipfs.tech/bitswap-protocol/>`_
* :doc:`examples` - Other py-libp2p examples
