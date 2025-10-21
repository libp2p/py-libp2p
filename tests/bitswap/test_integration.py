"""Integration tests for Bitswap file transfer between nodes."""

from pathlib import Path
import tempfile

import pytest
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.client import BitswapClient
from libp2p.bitswap.dag import MerkleDag
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr


class TestBitswapIntegration:
    """Integration tests for Bitswap protocol."""

    @pytest.mark.trio
    async def test_file_transfer_between_two_nodes(self):
        """Test complete file transfer between provider and client nodes."""
        async with trio.open_nursery() as nursery:
            # Create two hosts
            provider_key = create_new_key_pair()
            client_key = create_new_key_pair()

            provider_host = new_host(
                key_pair=provider_key,
                listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
            )
            client_host = new_host(
                key_pair=client_key,
                listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
            )

            # Start hosts
            nursery.start_soon(provider_host.run)
            nursery.start_soon(client_host.run)

            # Give hosts time to start
            await trio.sleep(0.1)

            # Create Bitswap clients
            provider_store = MemoryBlockStore()
            client_store = MemoryBlockStore()

            provider_bitswap = BitswapClient(provider_host, block_store=provider_store)
            client_bitswap = BitswapClient(client_host, block_store=client_store)

            # Start Bitswap clients
            await provider_bitswap.start()
            await client_bitswap.start()

            # Create test file
            test_data = b"Hello, Bitswap! " * 100  # Create some test data
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(test_data)
                tmp_file_path = tmp_file.name

            try:
                # Provider: Add file to DAG and store blocks
                provider_dag = MerkleDag(provider_bitswap, block_store=provider_store)
                root_cid = await provider_dag.add_file(str(tmp_file_path))

                # Verify provider has all blocks
                provider_cids = provider_store.get_all_cids()
                assert len(provider_cids) > 0
                assert root_cid in provider_cids

                # Connect client to provider
                provider_addrs = provider_host.get_addrs()
                assert len(provider_addrs) > 0

                provider_info = info_from_p2p_addr(
                    Multiaddr(f"{provider_addrs[0]}/p2p/{provider_host.get_id()}")
                )
                await client_host.connect(provider_info)

                # Give connection time to establish
                await trio.sleep(0.2)

                # Client: Request the file by root CID
                client_dag = MerkleDag(client_bitswap, block_store=client_store)

                # Get the file
                host_id = provider_host.get_id()
                retrieved_data = await client_dag.fetch_file(root_cid, host_id)

                # Verify the data matches
                assert retrieved_data == test_data

                # Verify client now has all blocks
                client_cids = client_store.get_all_cids()
                assert len(client_cids) == len(provider_cids)
                assert root_cid in client_cids

            finally:
                # Cleanup
                Path(tmp_file_path).unlink()
                await provider_bitswap.stop()
                await client_bitswap.stop()
                await provider_host.close()
                await client_host.close()
                nursery.cancel_scope.cancel()

    @pytest.mark.trio
    async def test_multiple_blocks_transfer(self):
        """Test transferring multiple independent blocks between nodes."""
        async with trio.open_nursery() as nursery:
            # Create two hosts
            provider_key = create_new_key_pair()
            client_key = create_new_key_pair()

            provider_host = new_host(
                key_pair=provider_key,
                listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
            )
            client_host = new_host(
                key_pair=client_key,
                listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
            )

            # Start hosts
            nursery.start_soon(provider_host.run)
            nursery.start_soon(client_host.run)

            await trio.sleep(0.1)

            # Create Bitswap clients
            provider_store = MemoryBlockStore()
            client_store = MemoryBlockStore()

            provider_bitswap = BitswapClient(provider_host, block_store=provider_store)
            client_bitswap = BitswapClient(client_host, block_store=client_store)

            await provider_bitswap.start()
            await client_bitswap.start()

            try:
                # Provider: Add multiple blocks
                from libp2p.bitswap.cid import compute_cid_v1

                blocks = {
                    b"block1": compute_cid_v1(b"block1"),
                    b"block2": compute_cid_v1(b"block2"),
                    b"block3": compute_cid_v1(b"block3"),
                }

                for data, cid in blocks.items():
                    await provider_store.put_block(cid, data)

                # Connect nodes
                provider_addrs = provider_host.get_addrs()
                provider_info = info_from_p2p_addr(
                    Multiaddr(f"{provider_addrs[0]}/p2p/{provider_host.get_id()}")
                )
                await client_host.connect(provider_info)

                await trio.sleep(0.2)

                # Client: Request all blocks
                for data, cid in blocks.items():
                    retrieved = await client_bitswap.get_block(
                        cid, peer_id=provider_host.get_id(), timeout=2.0
                    )
                    assert retrieved == data

                # Verify client has all blocks
                client_cids = client_store.get_all_cids()
                assert len(client_cids) == len(blocks)

            finally:
                await provider_bitswap.stop()
                await client_bitswap.stop()
                await provider_host.close()
                await client_host.close()
                nursery.cancel_scope.cancel()

    @pytest.mark.trio
    async def test_large_file_transfer(self):
        """Test transferring a large file that requires multiple chunks."""
        async with trio.open_nursery() as nursery:
            # Create hosts
            provider_key = create_new_key_pair()
            client_key = create_new_key_pair()

            provider_host = new_host(
                key_pair=provider_key,
                listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
            )
            client_host = new_host(
                key_pair=client_key,
                listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
            )

            nursery.start_soon(provider_host.run)
            nursery.start_soon(client_host.run)
            await trio.sleep(0.1)

            provider_store = MemoryBlockStore()
            client_store = MemoryBlockStore()

            provider_bitswap = BitswapClient(provider_host, block_store=provider_store)
            client_bitswap = BitswapClient(client_host, block_store=client_store)

            await provider_bitswap.start()
            await client_bitswap.start()

            # Create large test file (>256KB to ensure chunking)
            large_data = b"X" * (300 * 1024)  # 300KB
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(large_data)
                tmp_file_path = tmp_file.name

            try:
                # Provider: Add large file
                provider_dag = MerkleDag(provider_bitswap, block_store=provider_store)
                root_cid = await provider_dag.add_file(str(tmp_file_path))

                # Verify multiple blocks were created
                provider_cids = provider_store.get_all_cids()
                assert len(provider_cids) > 1  # Should be chunked

                # Connect nodes
                provider_addrs = provider_host.get_addrs()
                provider_info = info_from_p2p_addr(
                    Multiaddr(f"{provider_addrs[0]}/p2p/{provider_host.get_id()}")
                )
                await client_host.connect(provider_info)
                await trio.sleep(0.2)

                # Client: Get the file
                client_dag = MerkleDag(client_bitswap, block_store=client_store)
                host_id = provider_host.get_id()
                retrieved_data = await client_dag.fetch_file(root_cid, host_id)

                # Verify complete transfer
                assert len(retrieved_data) == len(large_data)
                assert retrieved_data == large_data

                # Verify all blocks transferred
                client_cids = client_store.get_all_cids()
                assert len(client_cids) == len(provider_cids)

            finally:
                Path(tmp_file_path).unlink()
                await provider_bitswap.stop()
                await client_bitswap.stop()
                await provider_host.close()
                await client_host.close()
                nursery.cancel_scope.cancel()

    @pytest.mark.trio
    async def test_bidirectional_exchange(self):
        """Test bidirectional block exchange between nodes."""
        async with trio.open_nursery() as nursery:
            # Create two hosts
            node1_key = create_new_key_pair()
            node2_key = create_new_key_pair()

            node1_host = new_host(
                key_pair=node1_key,
                listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
            )
            node2_host = new_host(
                key_pair=node2_key,
                listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
            )

            nursery.start_soon(node1_host.run)
            nursery.start_soon(node2_host.run)
            await trio.sleep(0.1)

            node1_store = MemoryBlockStore()
            node2_store = MemoryBlockStore()

            node1_bitswap = BitswapClient(node1_host, block_store=node1_store)
            node2_bitswap = BitswapClient(node2_host, block_store=node2_store)

            await node1_bitswap.start()
            await node2_bitswap.start()

            try:
                from libp2p.bitswap.cid import compute_cid_v1

                # Node1 has block A
                block_a = b"Block A content"
                cid_a = compute_cid_v1(block_a)
                await node1_store.put_block(cid_a, block_a)

                # Node2 has block B
                block_b = b"Block B content"
                cid_b = compute_cid_v1(block_b)
                await node2_store.put_block(cid_b, block_b)

                # Connect nodes
                node1_addrs = node1_host.get_addrs()
                node1_info = info_from_p2p_addr(
                    Multiaddr(f"{node1_addrs[0]}/p2p/{node1_host.get_id()}")
                )
                await node2_host.connect(node1_info)
                await trio.sleep(0.2)

                # Node1 requests block B from Node2
                retrieved_b = await node1_bitswap.get_block(
                    cid_b, peer_id=node2_host.get_id(), timeout=2.0
                )
                assert retrieved_b == block_b

                # Node2 requests block A from Node1
                retrieved_a = await node2_bitswap.get_block(
                    cid_a, peer_id=node1_host.get_id(), timeout=2.0
                )
                assert retrieved_a == block_a

                # Both nodes should now have both blocks
                node1_cids = node1_store.get_all_cids()
                node2_cids = node2_store.get_all_cids()

                assert cid_a in node1_cids and cid_b in node1_cids
                assert cid_a in node2_cids and cid_b in node2_cids

            finally:
                await node1_bitswap.stop()
                await node2_bitswap.stop()
                await node1_host.close()
                await node2_host.close()
                nursery.cancel_scope.cancel()
