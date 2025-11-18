Bitswap
=======

.. currentmodule:: libp2p.bitswap

The Bitswap protocol enables content discovery and file sharing in py-libp2p networks.

Subpackages
-----------

.. toctree::
   :maxdepth: 4

   libp2p.bitswap.pb

Overview
--------

Bitswap is a message-based protocol for exchanging content-addressed blocks between peers.
It is a core component of IPFS (InterPlanetary File System) and enables efficient
peer-to-peer file sharing.

Key Features
~~~~~~~~~~~~

* Content-addressed block storage and retrieval
* Wantlist-based block exchange
* Priority-based request handling
* Bidirectional peer communication
* Cancellation support for requests

Protocol Version
~~~~~~~~~~~~~~~~

This implementation supports **Bitswap 1.0.0** (``/ipfs/bitswap/1.0.0``).

Quick Start
-----------

Basic Usage
~~~~~~~~~~~

.. code-block:: python

    import trio
    from libp2p import new_host
    from libp2p.bitswap import BitswapClient
    import multiaddr

    async def main():
        # Create a host
        listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")
        host = new_host()

        async with host.run([listen_addr]), trio.open_nursery() as nursery:
            # Create Bitswap client
            bitswap = BitswapClient(host)
            bitswap.set_nursery(nursery)
            await bitswap.start()

            # Add a block
            cid = compute_cid(b"Hello, Bitswap!")
            await bitswap.add_block(cid, b"Hello, Bitswap!")

            # Request a block from a peer
            data = await bitswap.get_block(cid, peer_id, timeout=30)
            print(f"Received: {data}")

            await bitswap.stop()

    trio.run(main)

Running a Provider
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    async def run_provider():
        host = new_host()
        listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/4001")

        async with host.run([listen_addr]), trio.open_nursery() as nursery:
            bitswap = BitswapClient(host)
            bitswap.set_nursery(nursery)
            await bitswap.start()

            # Add blocks to serve
            blocks = [b"Block 1", b"Block 2", b"Block 3"]
            for data in blocks:
                cid = compute_cid(data)
                await bitswap.add_block(cid, data)

            print(f"Provider listening on {host.get_addrs()}")
            await trio.sleep_forever()

Running a Client
~~~~~~~~~~~~~~~~

.. code-block:: python

    async def run_client(provider_multiaddr):
        host = new_host()
        listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")

        # Parse provider address
        provider_info = info_from_p2p_addr(provider_multiaddr)

        async with host.run([listen_addr]), trio.open_nursery() as nursery:
            bitswap = BitswapClient(host)
            bitswap.set_nursery(nursery)
            await bitswap.start()

            # Connect to provider
            await host.connect(provider_info)

            # Request blocks
            wanted_cids = [...]  # List of CIDs to request
            for cid in wanted_cids:
                try:
                    data = await bitswap.get_block(cid, provider_info.peer_id)
                    print(f"Got block: {data}")
                except Exception as e:
                    print(f"Failed to get block: {e}")

API Reference
-------------

BitswapClient
~~~~~~~~~~~~~

.. autoclass:: BitswapClient
   :members:
   :undoc-members:
   :show-inheritance:

BlockStore
~~~~~~~~~~

.. autoclass:: BlockStore
   :members:
   :undoc-members:
   :show-inheritance:

MemoryBlockStore
~~~~~~~~~~~~~~~~

.. autoclass:: MemoryBlockStore
   :members:
   :undoc-members:
   :show-inheritance:

Configuration
~~~~~~~~~~~~~

.. automodule:: libp2p.bitswap.config
   :members:
   :undoc-members:

Errors
~~~~~~

.. automodule:: libp2p.bitswap.errors
   :members:
   :undoc-members:
   :show-inheritance:

Protocol Details
----------------

Message Format
~~~~~~~~~~~~~~

Bitswap messages use Protocol Buffers with the following structure:

.. code-block:: protobuf

    message Message {
      message Wantlist {
        message Entry {
          bytes block = 1;      // CID of the block
          int32 priority = 2;   // Priority (higher = more important)
          bool cancel = 3;      // Cancel a previous request
        }
        repeated Entry entries = 1;
        bool full = 2;          // Full wantlist or update
      }

      Wantlist wantlist = 1;
      repeated bytes blocks = 2;  // Block data
    }

Wire Protocol
~~~~~~~~~~~~~

Messages are sent as length-prefixed protobuf messages:

1. Message is serialized to protobuf bytes
2. Length is encoded as unsigned varint
3. Format: ``[varint length][protobuf message]``

Maximum message size: **4 MiB**

Maximum block size: **2 MiB**

Block Exchange Flow
~~~~~~~~~~~~~~~~~~~

1. **Client requests block**:

   - Check local block store
   - If not found, add to wantlist
   - Send wantlist to peer(s)
   - Wait for block response

2. **Server receives wantlist**:

   - Parse wantlist entries
   - Check local block store for requested blocks
   - Send available blocks to client

3. **Client receives blocks**:

   - Store blocks locally
   - Notify pending requests
   - Send cancel messages for received blocks

Wantlist Management
~~~~~~~~~~~~~~~~~~~

Bitswap maintains two types of wantlists:

* **Local wantlist**: Blocks this peer wants
* **Peer wantlists**: Blocks each connected peer wants

Wantlist updates can be:

* **Full** (``full = true``): Replace entire wantlist
* **Incremental** (``full = false``): Apply specific changes

Advanced Usage
--------------

Custom Block Store
~~~~~~~~~~~~~~~~~~

Implement a custom block store by subclassing ``BlockStore``:

.. code-block:: python

    from libp2p.bitswap import BlockStore
    from pathlib import Path
    from typing import Optional

    class FileBlockStore(BlockStore):
        def __init__(self, base_path: str):
            self.base_path = Path(base_path)
            self.base_path.mkdir(exist_ok=True)

        async def get_block(self, cid: bytes) -> Optional[bytes]:
            file_path = self.base_path / cid.hex()
            if file_path.exists():
                return file_path.read_bytes()
            return None

        async def put_block(self, cid: bytes, data: bytes) -> None:
            file_path = self.base_path / cid.hex()
            file_path.write_bytes(data)

        async def has_block(self, cid: bytes) -> bool:
            file_path = self.base_path / cid.hex()
            return file_path.exists()

        async def delete_block(self, cid: bytes) -> None:
            file_path = self.base_path / cid.hex()
            if file_path.exists():
                file_path.unlink()

    # Use the custom store
    bitswap = BitswapClient(host, FileBlockStore("/path/to/blocks"))

Priority-Based Requests
~~~~~~~~~~~~~~~~~~~~~~~

Request blocks with different priorities:

.. code-block:: python

    # High priority block
    await bitswap.want_block(critical_cid, priority=10)

    # Normal priority
    await bitswap.want_block(normal_cid, priority=1)

    # Low priority
    await bitswap.want_block(optional_cid, priority=0)

Blocks with higher priority values are served first.

Cancel Requests
~~~~~~~~~~~~~~~

Cancel a block request:

.. code-block:: python

    # Add to wantlist
    await bitswap.want_block(cid)

    # Later, if no longer needed
    await bitswap.cancel_want(cid)

This sends a cancel message to all peers that haven't responded yet.

Examples
--------

The ``examples/bitswap`` directory contains complete examples:

* **Provider mode**: Serve blocks to other peers
* **Client mode**: Request blocks from providers
* **Demo mode**: Automated demonstration

Run examples:

.. code-block:: bash

    # Provider
    python examples/bitswap/bitswap.py --mode provider

    # Provider with file
    python examples/bitswap/bitswap.py --mode provider --file myfile.txt

    # Client
    python examples/bitswap/bitswap.py --mode client --provider <multiaddr>

    # Demo
    python examples/bitswap/bitswap.py --mode demo

Limitations
-----------

Current Version Limitations
~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **CID Encoding**: Uses simplified SHA-256 hashing instead of proper CIDv0/CIDv1
* **Protocol Version**: Only supports Bitswap 1.0.0
* **Block Store**: Default implementation is in-memory only
* **No Peer Scoring**: No accounting or peer reputation system

Future Enhancements
~~~~~~~~~~~~~~~~~~~

Planned improvements:

* Support for Bitswap 1.1.0 (CIDv1 with prefix encoding)
* Support for Bitswap 1.2.0 (Have/DontHave responses)
* Proper CID library integration
* Persistent block storage
* Peer scoring and accounting
* Content routing integration with DHT

See Also
--------

* :doc:`examples.bitswap` - Example code and tutorials
* `Bitswap Protocol Specification <https://specs.ipfs.tech/bitswap-protocol/>`_
* `IPFS Documentation <https://docs.ipfs.tech/>`_
* :doc:`libp2p` - Main py-libp2p documentation
