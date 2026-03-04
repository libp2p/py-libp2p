"""
DAG-PB codec implementation for IPFS UnixFS.

This module provides encoding and decoding functionality for DAG-PB format,
which is used by IPFS to represent files and directories as Merkle DAGs.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
import logging

from .cid import CIDInput, cid_to_bytes
from .pb.dag_pb_pb2 import PBNode
from .pb.unixfs_pb2 import Data as PBUnixFSData

logger = logging.getLogger(__name__)


def _normalize_link_cid(cid: CIDInput) -> bytes:
    """Normalize CID input for DAG links while preserving raw-bytes compatibility."""
    if isinstance(cid, bytes):
        return cid
    return cid_to_bytes(cid)


@dataclass(init=False)
class Link:
    """Represents a link to another block in the DAG."""

    cid: bytes
    name: str = ""
    size: int = 0

    def __init__(self, cid: CIDInput, name: str = "", size: int = 0) -> None:
        """Initialize and normalize link CID input."""
        self.cid = _normalize_link_cid(cid)
        self.name = name
        self.size = size
        self.__post_init__()

    def __post_init__(self) -> None:
        """Validate link data."""
        if not isinstance(self.cid, bytes):
            raise TypeError(f"cid must be bytes, got {type(self.cid)}")
        if not isinstance(self.name, str):
            raise TypeError(f"name must be str, got {type(self.name)}")
        if not isinstance(self.size, int) or self.size < 0:
            raise TypeError(f"size must be non-negative int, got {self.size}")


@dataclass
class UnixFSData:
    """UnixFS data structure for file/directory metadata."""

    type: str  # 'file', 'directory', 'raw', 'metadata', 'symlink'
    data: bytes = b""
    filesize: int = 0
    blocksizes: list[int] = field(default_factory=list)
    hash_type: int = 0
    fanout: int = 0

    # Type name to enum mapping
    TYPE_MAP = {
        "raw": 0,
        "directory": 1,
        "file": 2,
        "metadata": 3,
        "symlink": 4,
        "hamt-shard": 5,
    }

    # Reverse mapping
    ENUM_TO_TYPE = {v: k for k, v in TYPE_MAP.items()}

    def __post_init__(self) -> None:
        """Validate UnixFS data."""
        if self.type not in self.TYPE_MAP:
            raise ValueError(
                f"Invalid type: {self.type}. "
                f"Must be one of {list(self.TYPE_MAP.keys())}"
            )


def encode_dag_pb(links: list[Link], unixfs_data: UnixFSData | None = None) -> bytes:
    """
    Encode links and UnixFS data as DAG-PB format.

    Args:
        links: List of links to other blocks
        unixfs_data: Optional UnixFS data structure

    Returns:
        Encoded DAG-PB bytes

    Example:
        >>> from libp2p.bitswap.cid import compute_cid_v1, CODEC_RAW
        >>> chunk1_data = b"chunk 1 data"
        >>> chunk1_cid = compute_cid_v1(chunk1_data, codec=CODEC_RAW)
        >>> links = [
        ...     Link(cid=chunk1_cid, name="chunk0", size=len(chunk1_data))
        ... ]
        >>> data = UnixFSData(type='file', filesize=len(chunk1_data))
        >>> encoded = encode_dag_pb(links, data)

    """
    # Create PBNode
    pb_node = PBNode()

    # Add links
    for link in links:
        pb_link = pb_node.Links.add()
        pb_link.Hash = link.cid
        pb_link.Name = link.name
        pb_link.Tsize = link.size

    # Add UnixFS data if provided
    if unixfs_data:
        # Create UnixFS data structure
        pb_unixfs = PBUnixFSData()
        pb_unixfs.Type = UnixFSData.TYPE_MAP[unixfs_data.type]  # type: ignore[assignment]
        pb_unixfs.Data = unixfs_data.data
        pb_unixfs.filesize = unixfs_data.filesize

        # Add blocksizes
        for blocksize in unixfs_data.blocksizes:
            pb_unixfs.blocksizes.append(blocksize)

        if unixfs_data.hash_type:
            pb_unixfs.hashType = unixfs_data.hash_type
        if unixfs_data.fanout:
            pb_unixfs.fanout = unixfs_data.fanout

        # Serialize UnixFS data and add to PBNode
        pb_node.Data = pb_unixfs.SerializeToString()

    # Serialize PBNode
    return pb_node.SerializeToString()


def decode_dag_pb(data: bytes) -> tuple[list[Link], UnixFSData | None]:
    """
    Decode DAG-PB format to links and UnixFS data.

    Args:
        data: Encoded DAG-PB bytes

    Returns:
        Tuple of (links, unixfs_data)

    Example:
        >>> encoded = encode_dag_pb(links, data)
        >>> decoded_links, decoded_data = decode_dag_pb(encoded)
        >>> for link in decoded_links:
        ...     print(f"Child CID: {link.cid.hex()[:16]}...")

    """
    # Parse PBNode
    pb_node = PBNode()
    pb_node.ParseFromString(data)

    # Extract links
    links = []
    for pb_link in pb_node.Links:
        link = Link(
            cid=pb_link.Hash,
            name=pb_link.Name if pb_link.Name else "",
            size=pb_link.Tsize,
        )
        links.append(link)

    # Extract UnixFS data if present
    unixfs_data = None
    if pb_node.Data:
        try:
            pb_unixfs = PBUnixFSData()
            pb_unixfs.ParseFromString(pb_node.Data)

            # Convert enum to string
            type_str = UnixFSData.ENUM_TO_TYPE.get(pb_unixfs.Type, "raw")

            unixfs_data = UnixFSData(
                type=type_str,
                data=pb_unixfs.Data if pb_unixfs.Data else b"",
                filesize=pb_unixfs.filesize if pb_unixfs.filesize else 0,
                blocksizes=list(pb_unixfs.blocksizes) if pb_unixfs.blocksizes else [],
                hash_type=pb_unixfs.hashType if pb_unixfs.hashType else 0,
                fanout=pb_unixfs.fanout if pb_unixfs.fanout else 0,
            )
        except Exception as e:
            # If UnixFS data parsing fails, treat as raw data
            logger.debug(f"Failed to parse UnixFS data: {e}")

    return links, unixfs_data


def create_file_node(chunks: Sequence[tuple[CIDInput, int]]) -> bytes:
    """
    Create a DAG-PB node for a file with multiple chunks.

    Args:
        chunks: List of (cid, size) tuples for each chunk

    Returns:
        Encoded DAG-PB node

    Example:
        >>> chunks = [(chunk1_cid, len(chunk1)), (chunk2_cid, len(chunk2))]
        >>> root_node = create_file_node(chunks)

    """
    links = []
    total_size = 0
    blocksizes = []

    for i, (cid, size) in enumerate(chunks):
        links.append(Link(cid=cid, name=f"chunk{i}", size=size))
        blocksizes.append(size)
        total_size += size

    unixfs_data = UnixFSData(type="file", filesize=total_size, blocksizes=blocksizes)

    return encode_dag_pb(links, unixfs_data)


def create_directory_node(entries: Sequence[tuple[str, CIDInput, int]]) -> bytes:
    """
    Create a DAG-PB node for a directory.

    Args:
        entries: List of (name, cid, size) tuples for each entry

    Returns:
        Encoded DAG-PB node

    Example:
        >>> entries = [
        ...     ("file1.txt", file1_cid, 1024),
        ...     ("file2.txt", file2_cid, 2048),
        ... ]
        >>> dir_node = create_directory_node(entries)

    """
    links = []

    for name, cid, size in entries:
        links.append(Link(cid=cid, name=name, size=size))

    unixfs_data = UnixFSData(type="directory")

    return encode_dag_pb(links, unixfs_data)


def _get_unixfs_data(data: bytes) -> UnixFSData | None:
    """
    Safely extract UnixFS data from DAG-PB node.

    Returns None if the data cannot be decoded or is invalid.
    """
    try:
        _, unixfs_data = decode_dag_pb(data)
        return unixfs_data
    except Exception as e:
        logger.debug(f"Failed to extract UnixFS data: {e}")
        return None


def is_file_node(data: bytes) -> bool:
    """Check if DAG-PB node represents a file."""
    unixfs_data = _get_unixfs_data(data)
    return unixfs_data is not None and unixfs_data.type == "file"


def is_directory_node(data: bytes) -> bool:
    """Check if DAG-PB node represents a directory."""
    unixfs_data = _get_unixfs_data(data)
    return unixfs_data is not None and unixfs_data.type == "directory"


def get_file_size(data: bytes) -> int:
    """Get the total file size from a DAG-PB file node."""
    unixfs_data = _get_unixfs_data(data)
    if unixfs_data and unixfs_data.type == "file":
        return unixfs_data.filesize
    return 0
