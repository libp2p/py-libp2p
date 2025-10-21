"""Tests for DAG-PB encoder/decoder."""

import pytest

from libp2p.bitswap.cid import CODEC_RAW, compute_cid_v1
from libp2p.bitswap.dag_pb import (
    Link,
    UnixFSData,
    create_directory_node,
    create_file_node,
    decode_dag_pb,
    encode_dag_pb,
    get_file_size,
    is_directory_node,
    is_file_node,
)


class TestLink:
    """Test Link dataclass."""

    def test_link_creation(self):
        """Test creating a Link."""
        cid = b"\x01\x23\x45\x67" * 8
        link = Link(cid=cid, name="file.txt", size=1024)

        assert link.cid == cid
        assert link.name == "file.txt"
        assert link.size == 1024

    def test_link_optional_fields(self):
        """Test Link with optional fields."""
        cid = b"\x01\x23\x45\x67" * 8
        link = Link(cid=cid)

        assert link.cid == cid
        assert link.name == ""
        assert link.size == 0


class TestUnixFSData:
    """Test UnixFSData dataclass."""

    def test_unixfs_file(self):
        """Test creating UnixFS file metadata."""
        data = UnixFSData(
            type="file",
            data=b"hello",
            filesize=1000,
            blocksizes=[256, 256, 256, 232],
        )

        assert data.type == "file"
        assert data.data == b"hello"
        assert data.filesize == 1000
        assert len(data.blocksizes) == 4
        assert sum(data.blocksizes) == 1000

    def test_unixfs_directory(self):
        """Test creating UnixFS directory metadata."""
        data = UnixFSData(type="directory")

        assert data.type == "directory"
        assert data.data == b""
        assert data.filesize == 0


class TestEncodeDecode:
    """Test encoding and decoding DAG-PB."""

    def test_encode_decode_no_links(self):
        """Test encoding/decoding with no links."""
        # Encode
        original_data = UnixFSData(type="file", data=b"small file")
        encoded = encode_dag_pb(links=[], unixfs_data=original_data)

        # Decode
        links, data = decode_dag_pb(encoded)

        # Verify
        assert len(links) == 0
        assert data is not None
        assert data.type == "file"
        assert data.data == b"small file"

    def test_encode_decode_with_links(self):
        """Test encoding/decoding with links."""
        # Create test chunks
        chunk1 = b"chunk1" * 100
        chunk2 = b"chunk2" * 100

        cid1 = compute_cid_v1(chunk1, codec=CODEC_RAW)
        cid2 = compute_cid_v1(chunk2, codec=CODEC_RAW)

        # Create links
        original_links = [
            Link(cid=cid1, name="chunk1", size=len(chunk1)),
            Link(cid=cid2, name="chunk2", size=len(chunk2)),
        ]

        # Create metadata
        original_data = UnixFSData(
            type="file",
            filesize=len(chunk1) + len(chunk2),
            blocksizes=[len(chunk1), len(chunk2)],
        )

        # Encode
        encoded = encode_dag_pb(links=original_links, unixfs_data=original_data)

        # Decode
        links, data = decode_dag_pb(encoded)

        # Verify links
        assert len(links) == 2
        assert links[0].cid == cid1
        assert links[0].name == "chunk1"
        assert links[0].size == len(chunk1)
        assert links[1].cid == cid2
        assert links[1].name == "chunk2"
        assert links[1].size == len(chunk2)

        # Verify metadata
        assert data is not None
        assert data.type == "file"
        assert data.filesize == len(chunk1) + len(chunk2)
        assert data.blocksizes == [len(chunk1), len(chunk2)]

    def test_encode_decode_round_trip(self):
        """Test multiple encode/decode round trips."""
        chunk = b"test" * 1000
        cid = compute_cid_v1(chunk, codec=CODEC_RAW)

        links = [Link(cid=cid, size=len(chunk))]
        unixfs_data = UnixFSData(
            type="file", filesize=len(chunk), blocksizes=[len(chunk)]
        )

        # First round
        encoded1 = encode_dag_pb(links, unixfs_data)
        decoded_links1, decoded_data1 = decode_dag_pb(encoded1)

        # Second round
        encoded2 = encode_dag_pb(decoded_links1, decoded_data1)
        decoded_links2, decoded_data2 = decode_dag_pb(encoded2)

        # Should be identical
        assert encoded1 == encoded2
        assert decoded_links1[0].cid == decoded_links2[0].cid
        assert decoded_data1 is not None and decoded_data2 is not None
        assert decoded_data1.filesize == decoded_data2.filesize

    def test_decode_invalid_data(self):
        """Test decoding invalid data."""
        with pytest.raises(Exception):
            decode_dag_pb(b"invalid protobuf data")


class TestFileNode:
    """Test file node helpers."""

    def test_create_file_node_single_chunk(self):
        """Test creating file node with single chunk."""
        chunk = b"data" * 1000
        cid = compute_cid_v1(chunk, codec=CODEC_RAW)

        node_data = create_file_node([(cid, len(chunk))])
        links, unixfs_data = decode_dag_pb(node_data)

        assert len(links) == 1
        assert links[0].cid == cid
        assert links[0].size == len(chunk)
        assert unixfs_data is not None
        assert unixfs_data.type == "file"
        assert unixfs_data.filesize == len(chunk)

    def test_create_file_node_multiple_chunks(self):
        """Test creating file node with multiple chunks."""
        chunks = [b"chunk1" * 100, b"chunk2" * 200, b"chunk3" * 150]
        chunks_data = [
            (compute_cid_v1(chunk, codec=CODEC_RAW), len(chunk)) for chunk in chunks
        ]

        node_data = create_file_node(chunks_data)
        links, unixfs_data = decode_dag_pb(node_data)

        assert len(links) == 3
        assert unixfs_data is not None
        total_size = sum(len(chunk) for chunk in chunks)
        assert unixfs_data.filesize == total_size
        assert sum(unixfs_data.blocksizes) == total_size

    def test_is_file_node(self):
        """Test file node detection."""
        chunk = b"test"
        cid = compute_cid_v1(chunk, codec=CODEC_RAW)

        # Create file node
        file_node = create_file_node([(cid, len(chunk))])
        assert is_file_node(file_node) is True

        # Create directory node
        dir_node = create_directory_node([])
        assert is_file_node(dir_node) is False

    def test_get_file_size(self):
        """Test getting file size from node."""
        chunks = [b"a" * 100, b"b" * 200]
        chunks_data = [
            (compute_cid_v1(chunk, codec=CODEC_RAW), len(chunk)) for chunk in chunks
        ]

        node_data = create_file_node(chunks_data)
        size = get_file_size(node_data)

        assert size == 300


class TestDirectoryNode:
    """Test directory node helpers."""

    def test_create_directory_node_empty(self):
        """Test creating empty directory."""
        node_data = create_directory_node([])
        links, unixfs_data = decode_dag_pb(node_data)

        assert len(links) == 0
        assert unixfs_data is not None
        assert unixfs_data.type == "directory"

    def test_create_directory_node_with_entries(self):
        """Test creating directory with entries."""
        # Create some "files"
        file1 = b"file1" * 100
        file2 = b"file2" * 200

        cid1 = compute_cid_v1(file1, codec=CODEC_RAW)
        cid2 = compute_cid_v1(file2, codec=CODEC_RAW)

        entries = [
            ("file1.txt", cid1, len(file1)),
            ("file2.txt", cid2, len(file2)),
        ]

        node_data = create_directory_node(entries)
        links, unixfs_data = decode_dag_pb(node_data)

        assert len(links) == 2
        assert links[0].name == "file1.txt"
        assert links[0].cid == cid1
        assert links[1].name == "file2.txt"
        assert links[1].cid == cid2
        assert unixfs_data is not None
        assert unixfs_data.type == "directory"

    def test_is_directory_node(self):
        """Test directory node detection."""
        dir_node = create_directory_node([])
        assert is_directory_node(dir_node) is True

        chunk = b"test"
        cid = compute_cid_v1(chunk, codec=CODEC_RAW)
        file_node = create_file_node([(cid, len(chunk))])
        assert is_directory_node(file_node) is False


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_links_and_data(self):
        """Test encoding with no links and no data."""
        encoded = encode_dag_pb(links=[], unixfs_data=None)
        links, data = decode_dag_pb(encoded)

        assert len(links) == 0
        assert data is None

    def test_large_number_of_links(self):
        """Test with many links."""
        # Create 1000 links
        chunk = b"x" * 100
        cid = compute_cid_v1(chunk, codec=CODEC_RAW)

        links = [Link(cid=cid, name=f"chunk{i}", size=100) for i in range(1000)]

        encoded = encode_dag_pb(links=links)
        decoded_links, _ = decode_dag_pb(encoded)

        assert len(decoded_links) == 1000

    def test_large_inline_data(self):
        """Test with large inline data."""
        # 1 MB of inline data
        large_data = b"x" * (1024 * 1024)
        unixfs_data = UnixFSData(type="file", data=large_data)

        encoded = encode_dag_pb(links=[], unixfs_data=unixfs_data)
        _, decoded_data = decode_dag_pb(encoded)

        assert decoded_data is not None
        assert len(decoded_data.data) == 1024 * 1024

    def test_unicode_names(self):
        """Test with unicode filenames."""
        chunk = b"test"
        cid = compute_cid_v1(chunk, codec=CODEC_RAW)

        links = [
            Link(cid=cid, name="файл.txt", size=100),  # Russian
            Link(cid=cid, name="文件.txt", size=100),  # Chinese
            Link(cid=cid, name="📄.txt", size=100),  # Emoji
        ]

        encoded = encode_dag_pb(links=links)
        decoded_links, _ = decode_dag_pb(encoded)

        assert decoded_links[0].name == "файл.txt"
        assert decoded_links[1].name == "文件.txt"
        assert decoded_links[2].name == "📄.txt"
