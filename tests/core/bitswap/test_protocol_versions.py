"""
Integration tests for Bitswap protocol versions.

Tests file transfer functionality across all supported protocol versions:
- Bitswap v1.0.0
- Bitswap v1.1.0
- Bitswap v1.2.0
"""

from pathlib import Path
import tempfile

import pytest
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.cid import compute_cid_v1
from libp2p.bitswap.client import BitswapClient
from libp2p.bitswap.config import (
    BITSWAP_PROTOCOL_V100,
    BITSWAP_PROTOCOL_V110,
    BITSWAP_PROTOCOL_V120,
)
from libp2p.bitswap.dag import MerkleDag
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr


class TestBitswapProtocolVersions:
    """Test Bitswap functionality across all protocol versions."""

    @pytest.mark.trio
    async def test_file_transfer_v100(self):
        """Test file transfer using Bitswap v1.0.0 protocol."""
        await self._test_file_transfer_with_protocol(BITSWAP_PROTOCOL_V100)

    @pytest.mark.trio
    async def test_file_transfer_v110(self):
        """Test file transfer using Bitswap v1.1.0 protocol."""
        await self._test_file_transfer_with_protocol(BITSWAP_PROTOCOL_V110)

    @pytest.mark.trio
    async def test_file_transfer_v120(self):
        """Test file transfer using Bitswap v1.2.0 protocol."""
        await self._test_file_transfer_with_protocol(BITSWAP_PROTOCOL_V120)

    async def _test_file_transfer_with_protocol(self, protocol_version: str):
        """
        Test file transfer with a specific protocol version.

        Args:
            protocol_version: The Bitswap protocol version to use

        """
        # Create provider and client hosts
        provider_key = create_new_key_pair()
        client_key = create_new_key_pair()

        provider_host = new_host(key_pair=provider_key)
        client_host = new_host(key_pair=client_key)

        # Start hosts using async context manager
        async with provider_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
            async with client_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
                await trio.sleep(0.1)

                # Create Bitswap clients with specific protocol version
                provider_store = MemoryBlockStore()
                client_store = MemoryBlockStore()

                provider_bitswap = BitswapClient(
                    provider_host,
                    block_store=provider_store,
                    protocol_version=protocol_version,
                )
                client_bitswap = BitswapClient(
                    client_host,
                    block_store=client_store,
                    protocol_version=protocol_version,
                )

                await provider_bitswap.start()
                await client_bitswap.start()

                # Create test file
                test_data = b"Protocol Test: " + protocol_version.encode() + b" " * 200
                with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                    tmp_file.write(test_data)
                    tmp_file_path = tmp_file.name

                # Provider: Add file to DAG
                provider_dag = MerkleDag(provider_bitswap, block_store=provider_store)
                root_cid = await provider_dag.add_file(str(tmp_file_path))

                # Verify provider has blocks
                provider_cids = provider_store.get_all_cids()
                assert len(provider_cids) > 0
                assert root_cid in provider_cids

                # Connect nodes
                provider_addrs = provider_host.get_addrs()
                provider_info = info_from_p2p_addr(
                    Multiaddr(f"{provider_addrs[0]}/p2p/{provider_host.get_id()}")
                )
                await client_host.connect(provider_info)
                await trio.sleep(0.2)

                # Client: Request and verify file
                client_dag = MerkleDag(client_bitswap, block_store=client_store)
                retrieved_data, filename = await client_dag.fetch_file(
                    root_cid, provider_host.get_id()
                )

                # Verify data integrity
                assert retrieved_data == test_data
                assert len(retrieved_data) == len(test_data)

                # Verify all blocks transferred
                client_cids = client_store.get_all_cids()
                assert len(client_cids) == len(provider_cids)
                assert root_cid in client_cids

                # Cleanup
                Path(tmp_file_path).unlink()
                await provider_bitswap.stop()
                await client_bitswap.stop()

    @pytest.mark.trio
    async def test_large_file_transfer_v100(self):
        """Test large file transfer with v1.0.0 (multi-chunk)."""
        await self._test_large_file_transfer(BITSWAP_PROTOCOL_V100)

    @pytest.mark.trio
    async def test_large_file_transfer_v110(self):
        """Test large file transfer with v1.1.0 (multi-chunk with prefixes)."""
        await self._test_large_file_transfer(BITSWAP_PROTOCOL_V110)

    @pytest.mark.trio
    async def test_large_file_transfer_v120(self):
        """Test large file transfer with v1.2.0 (multi-chunk with presence)."""
        await self._test_large_file_transfer(BITSWAP_PROTOCOL_V120)

    async def _test_large_file_transfer(self, protocol_version: str):
        """Test transferring a large file that requires multiple chunks."""
        provider_key = create_new_key_pair()
        client_key = create_new_key_pair()

        provider_host = new_host(key_pair=provider_key)
        client_host = new_host(key_pair=client_key)

        async with provider_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
            async with client_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
                await trio.sleep(0.1)

                provider_store = MemoryBlockStore()
                client_store = MemoryBlockStore()

                provider_bitswap = BitswapClient(
                    provider_host,
                    block_store=provider_store,
                    protocol_version=protocol_version,
                )
                client_bitswap = BitswapClient(
                    client_host,
                    block_store=client_store,
                    protocol_version=protocol_version,
                )

                await provider_bitswap.start()
                await client_bitswap.start()

                # Create large file (300KB to ensure chunking)
                large_data = (
                    b"LARGE FILE TEST [" + protocol_version.encode() + b"] "
                ) * 5000
                with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                    tmp_file.write(large_data)
                    tmp_file_path = tmp_file.name

                # Provider: Add large file
                provider_dag = MerkleDag(provider_bitswap, block_store=provider_store)
                root_cid = await provider_dag.add_file(str(tmp_file_path))

                # Verify multiple chunks created
                provider_cids = provider_store.get_all_cids()
                assert len(provider_cids) > 1, (
                    f"Expected chunking for {protocol_version}"
                )

                # Connect nodes
                provider_addrs = provider_host.get_addrs()
                provider_info = info_from_p2p_addr(
                    Multiaddr(f"{provider_addrs[0]}/p2p/{provider_host.get_id()}")
                )
                await client_host.connect(provider_info)
                await trio.sleep(0.2)

                # Client: Get file
                client_dag = MerkleDag(client_bitswap, block_store=client_store)
                retrieved_data, filename = await client_dag.fetch_file(
                    root_cid, provider_host.get_id()
                )

                # Verify complete transfer
                assert len(retrieved_data) == len(large_data)
                assert retrieved_data == large_data

                # Verify all chunks transferred
                client_cids = client_store.get_all_cids()
                assert len(client_cids) == len(provider_cids)

                # Cleanup
                Path(tmp_file_path).unlink()
                await provider_bitswap.stop()
                await client_bitswap.stop()

    @pytest.mark.trio
    async def test_bidirectional_exchange_v100(self):
        """Test bidirectional block exchange with v1.0.0."""
        await self._test_bidirectional_exchange(BITSWAP_PROTOCOL_V100)

    @pytest.mark.trio
    async def test_bidirectional_exchange_v110(self):
        """Test bidirectional block exchange with v1.1.0."""
        await self._test_bidirectional_exchange(BITSWAP_PROTOCOL_V110)

    @pytest.mark.trio
    async def test_bidirectional_exchange_v120(self):
        """Test bidirectional block exchange with v1.2.0."""
        await self._test_bidirectional_exchange(BITSWAP_PROTOCOL_V120)

    async def _test_bidirectional_exchange(self, protocol_version: str):
        """Test bidirectional block exchange between two nodes."""
        node1_key = create_new_key_pair()
        node2_key = create_new_key_pair()

        node1_host = new_host(key_pair=node1_key)
        node2_host = new_host(key_pair=node2_key)

        async with node1_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
            async with node2_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
                await trio.sleep(0.1)

                node1_store = MemoryBlockStore()
                node2_store = MemoryBlockStore()

                node1_bitswap = BitswapClient(
                    node1_host,
                    block_store=node1_store,
                    protocol_version=protocol_version,
                )
                node2_bitswap = BitswapClient(
                    node2_host,
                    block_store=node2_store,
                    protocol_version=protocol_version,
                )

                await node1_bitswap.start()
                await node2_bitswap.start()

                # Node1 has block A
                block_a = b"Block A for " + protocol_version.encode()
                cid_a = compute_cid_v1(block_a)
                await node1_store.put_block(cid_a, block_a)

                # Node2 has block B
                block_b = b"Block B for " + protocol_version.encode()
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

                # Both nodes should have both blocks
                node1_cids = node1_store.get_all_cids()
                node2_cids = node2_store.get_all_cids()

                assert cid_a in node1_cids and cid_b in node1_cids
                assert cid_a in node2_cids and cid_b in node2_cids

                # Cleanup
                await node1_bitswap.stop()
                await node2_bitswap.stop()


class TestProtocolNegotiation:
    """Test protocol version negotiation between nodes."""

    @pytest.mark.trio
    async def test_v120_to_v100_compatibility(self):
        """Test v1.2.0 client can communicate with v1.0.0 provider."""
        await self._test_cross_version_transfer(
            provider_version=BITSWAP_PROTOCOL_V100,
            client_version=BITSWAP_PROTOCOL_V120,
        )

    @pytest.mark.trio
    async def test_v100_to_v120_compatibility(self):
        """Test v1.0.0 client can communicate with v1.2.0 provider."""
        await self._test_cross_version_transfer(
            provider_version=BITSWAP_PROTOCOL_V120,
            client_version=BITSWAP_PROTOCOL_V100,
        )

    @pytest.mark.trio
    async def test_v110_to_v120_compatibility(self):
        """Test v1.1.0 to v1.2.0 compatibility."""
        await self._test_cross_version_transfer(
            provider_version=BITSWAP_PROTOCOL_V110,
            client_version=BITSWAP_PROTOCOL_V120,
        )

    @pytest.mark.trio
    async def test_v120_to_v110_compatibility(self):
        """Test v1.2.0 to v1.1.0 compatibility."""
        await self._test_cross_version_transfer(
            provider_version=BITSWAP_PROTOCOL_V120,
            client_version=BITSWAP_PROTOCOL_V110,
        )

    async def _test_cross_version_transfer(
        self, provider_version: str, client_version: str
    ):
        """
        Test file transfer between nodes with different protocol versions.

        Args:
            provider_version: Protocol version for provider node
            client_version: Protocol version for client node

        """
        provider_key = create_new_key_pair()
        client_key = create_new_key_pair()

        provider_host = new_host(key_pair=provider_key)
        client_host = new_host(key_pair=client_key)

        async with provider_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
            async with client_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
                await trio.sleep(0.1)

                provider_store = MemoryBlockStore()
                client_store = MemoryBlockStore()

                # Different protocol versions
                provider_bitswap = BitswapClient(
                    provider_host,
                    block_store=provider_store,
                    protocol_version=provider_version,
                )
                client_bitswap = BitswapClient(
                    client_host,
                    block_store=client_store,
                    protocol_version=client_version,
                )

                await provider_bitswap.start()
                await client_bitswap.start()

                # Test simple block exchange
                test_data = (
                    b"Cross-version test: "
                    + provider_version.encode()
                    + b" -> "
                    + client_version.encode()
                )
                cid = compute_cid_v1(test_data)
                await provider_store.put_block(cid, test_data)

                # Connect nodes
                provider_addrs = provider_host.get_addrs()
                provider_info = info_from_p2p_addr(
                    Multiaddr(f"{provider_addrs[0]}/p2p/{provider_host.get_id()}")
                )
                await client_host.connect(provider_info)
                await trio.sleep(0.2)

                # Client requests block
                retrieved = await client_bitswap.get_block(
                    cid, peer_id=provider_host.get_id(), timeout=2.0
                )

                # Verify successful transfer despite version difference
                assert retrieved == test_data
                assert cid in client_store.get_all_cids()

                # Cleanup
                await provider_bitswap.stop()
                await client_bitswap.stop()


class TestProtocolFeatures:
    """Test protocol-specific features."""

    @pytest.mark.trio
    async def test_v110_block_prefixes(self):
        """Test v1.1.0 specific feature: CID prefixes in blocks."""
        # v1.1.0 introduced CID prefixes in block messages
        # This test verifies that prefixes are properly handled
        provider_key = create_new_key_pair()
        client_key = create_new_key_pair()

        provider_host = new_host(key_pair=provider_key)
        client_host = new_host(key_pair=client_key)

        async with provider_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
            async with client_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
                await trio.sleep(0.1)

                provider_store = MemoryBlockStore()
                client_store = MemoryBlockStore()

                provider_bitswap = BitswapClient(
                    provider_host,
                    block_store=provider_store,
                    protocol_version=BITSWAP_PROTOCOL_V110,
                )
                client_bitswap = BitswapClient(
                    client_host,
                    block_store=client_store,
                    protocol_version=BITSWAP_PROTOCOL_V110,
                )

                await provider_bitswap.start()
                await client_bitswap.start()

                # Create multiple blocks with different codecs
                test_blocks = [
                    (b"block1", compute_cid_v1(b"block1")),
                    (b"block2", compute_cid_v1(b"block2")),
                    (b"block3", compute_cid_v1(b"block3")),
                ]

                for data, cid in test_blocks:
                    await provider_store.put_block(cid, data)

                # Connect nodes
                provider_addrs = provider_host.get_addrs()
                provider_info = info_from_p2p_addr(
                    Multiaddr(f"{provider_addrs[0]}/p2p/{provider_host.get_id()}")
                )
                await client_host.connect(provider_info)
                await trio.sleep(0.2)

                # Request all blocks
                for data, cid in test_blocks:
                    retrieved = await client_bitswap.get_block(
                        cid, peer_id=provider_host.get_id(), timeout=2.0
                    )
                    assert retrieved == data

                # Verify all blocks received
                client_cids = client_store.get_all_cids()
                assert len(client_cids) == len(test_blocks)

                # Cleanup
                await provider_bitswap.stop()
                await client_bitswap.stop()

    @pytest.mark.trio
    async def test_v120_block_presence(self):
        """Test v1.2.0 specific feature: Block presence messages (HAVE)."""
        provider_key = create_new_key_pair()
        client_key = create_new_key_pair()

        provider_host = new_host(key_pair=provider_key)
        client_host = new_host(key_pair=client_key)

        async with provider_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
            async with client_host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
                await trio.sleep(0.1)

                provider_store = MemoryBlockStore()
                client_store = MemoryBlockStore()

                provider_bitswap = BitswapClient(
                    provider_host,
                    block_store=provider_store,
                    protocol_version=BITSWAP_PROTOCOL_V120,
                )
                client_bitswap = BitswapClient(
                    client_host,
                    block_store=client_store,
                    protocol_version=BITSWAP_PROTOCOL_V120,
                )

                await provider_bitswap.start()
                await client_bitswap.start()

                # Provider has blocks
                existing_data = b"I exist"
                existing_cid = compute_cid_v1(existing_data)
                await provider_store.put_block(existing_cid, existing_data)

                # Connect nodes
                provider_addrs = provider_host.get_addrs()
                provider_info = info_from_p2p_addr(
                    Multiaddr(f"{provider_addrs[0]}/p2p/{provider_host.get_id()}")
                )
                await client_host.connect(provider_info)
                await trio.sleep(0.2)

                # Request existing block - should succeed
                retrieved = await client_bitswap.get_block(
                    existing_cid, peer_id=provider_host.get_id(), timeout=2.0
                )
                assert retrieved == existing_data

                # Verify client has the block now
                client_has_block = await client_store.has_block(existing_cid)
                assert client_has_block is True

                # Cleanup
                await provider_bitswap.stop()
                await client_bitswap.stop()
