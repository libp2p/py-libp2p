Bitswap File Sharing
====================

This example demonstrates peer-to-peer file sharing using the Bitswap protocol with Merkle DAG structure.

What is Bitswap?
----------------

Bitswap is a data exchange protocol that enables peers to request and share content-addressed blocks.
Files are split into blocks, organized in a Merkle DAG (Directed Acyclic Graph), and transferred efficiently between peers.

Quick Start
-----------

**Start a provider to share a file:**

.. code-block:: bash

    python examples/bitswap/bitswap.py --mode provider --file myfile.pdf

**Download the file from another machine:**

.. code-block:: bash

    python examples/bitswap/bitswap.py --mode client \
        --provider "/ip4/192.168.1.10/tcp/8000/p2p/QmXXX..." \
        --cid "017012207b..."

Usage
-----

Provider Mode
~~~~~~~~~~~~~

Share a file with other peers:

.. code-block:: bash

    # Share a file (auto port)
    python bitswap.py --mode provider --file document.pdf

    # Share on specific port
    python bitswap.py --mode provider --file photo.jpg --port 8000

The provider will:

1. Create a Merkle DAG from the file
2. Store all blocks in memory
3. Display the root CID and connection command
4. Wait for client connections

Client Mode
~~~~~~~~~~~

Download a file from a provider:

.. code-block:: bash

    python bitswap.py --mode client \
        --provider "/ip4/192.168.1.10/tcp/8000/p2p/QmProviderID..." \
        --cid "01701220abc..."

    # Specify output directory
    python bitswap.py --mode client \
        --provider "<multiaddr>" \
        --cid "<root_cid>" \
        --output ~/Downloads

The client will:

1. Connect to the provider
2. Request blocks by CID
3. Reconstruct the file from blocks
4. Save to disk with original filename

How It Works
------------

The implementation uses a Merkle DAG structure for all files:

1. **File Chunking**: Files are split into 256KB blocks
2. **DAG Creation**: Blocks are organized in a tree structure
3. **Root CID**: A single identifier for the entire file
4. **Block Exchange**: Client requests blocks, provider sends them
5. **Reconstruction**: Client rebuilds file from blocks

Example Session
---------------

Provider Output
~~~~~~~~~~~~~~~

.. code-block:: text

    ======================================================================
    PROVIDER NODE STARTING
    ======================================================================
    File: document.pdf
    Size: 2.5 MB
    Port: auto
    ======================================================================
    Peer ID: QmSK4bN4fDCxwvSVYvxxgHex2wob6VwzpEfpw8hc2Xxbow
    Listening on 2 address(es):
      /ip4/192.168.1.101/tcp/50182/p2p/QmSK4bN4fDCxwvSVYvxxgHex2wob6VwzpEfpw8hc2Xxbow
      /ip4/127.0.0.1/tcp/50182/p2p/QmSK4bN4fDCxwvSVYvxxgHex2wob6VwzpEfpw8hc2Xxbow
    ✓ Bitswap started

    Adding file to DAG...
      📤 completed: 100.0% (2.5 MB/2.5 MB)

    ======================================================================
    FILE READY TO SHARE!
    ======================================================================
    Root CID:  01701220336d0f55eac9b5536e1d5f4a5429bbc9a7343f1e1d19b7757baf76b61f4f4731

    📋 COPY THIS COMMAND TO RUN CLIENT:
    ======================================================================
    python bitswap.py --mode client --provider "..." --cid "..."
    ======================================================================

    Provider is running. Press Ctrl+C to stop...

Client Output
~~~~~~~~~~~~~

.. code-block:: text

    ======================================================================
    CLIENT NODE STARTING
    ======================================================================
    Provider:   /ip4/192.168.1.101/tcp/50182/p2p/QmSK4b...
    Root CID:   01701220336d0f55eac9b5536e1d5f4a5429bbc9a7343f1e...
    Output dir: /tmp
    ======================================================================
    Client Peer ID: QmTaLxNyPszMamvE7X8oYaso1eFceB8Dqjqo3v157kfioY
    ✓ Bitswap started

    Connecting to provider...
    ✓ Connected

    Fetching file...

    ======================================================================
    FETCH STATISTICS:
    ======================================================================
    Total blocks fetched: 12
      ✓ 1. 01701220... (256.0 KB)
      ✓ 2. 01551220... (256.0 KB)
      ...

    ======================================================================
    FILE DOWNLOADED!
    ======================================================================
    Size: 2.5 MB
    Filename: document.pdf (from metadata)
    ✓ Saved to: /tmp/document.pdf
    ======================================================================

Features
--------

* **Content Addressing**: Files identified by cryptographic hash (CID)
* **Merkle DAG Structure**: Efficient handling of files of any size
* **Block-level Transfer**: Parallel block fetching for speed
* **File Metadata**: Original filename preserved in DAG
* **Resume Support**: Can request specific missing blocks
* **Integrity Verification**: All blocks verified by CID

See Also
--------

* :doc:`libp2p.bitswap` - Bitswap API documentation
* `Bitswap Protocol Specification <https://specs.ipfs.tech/bitswap-protocol/>`_
* :doc:`examples` - Other py-libp2p examples
