"""
DAG-PB codec implementation for IPFS UnixFS.

This module provides encoding and decoding functionality for DAG-PB format,
which is used by IPFS to represent files and directories as Merkle DAGs.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import logging

from .cid import CODEC_DAG_PB, CIDInput, cid_to_bytes, compute_cid_v1
from .pb.dag_pb_pb2 import PBLink, PBNode
from .pb.unixfs_pb2 import Data as PBUnixFSData

# Maximum links per internal DAG-PB node — matches Go's balanced.Layout default
MAX_LINKS_PER_NODE = 174

logger = logging.getLogger(__name__)


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    buf = []
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def _normalize_link_cid(cid: CIDInput) -> bytes:
    """
    Normalize CID input for DAG links while preserving raw-bytes compatibility.

    DAG-PB links store only the multihash (not the full CID with version/codec).
    This matches Kubo's behavior and the DAG-PB specification.
    """
    from .cid import parse_cid

    # Always parse the CID and extract the multihash
    # This handles both CID objects and raw bytes (whether CIDv0, CIDv1, or already a multihash)
    cid_obj = parse_cid(cid)
    return cid_obj.multihash


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
    # DAG-PB canonical format requires Links (field 2) BEFORE Data (field 1).
    # Standard protobuf SerializeToString() emits fields in field-number order
    # (Data=1 first, Links=2 second), producing different bytes and a different
    # CID than Kubo for the same logical content.
    # We manually construct the wire format to enforce the correct ordering.

    result = b""

    # 1. Serialize each Link first — field 2, wire type 2 (length-delimited) = tag 0x12
    for link in links:
        pb_link = PBLink()
        pb_link.Hash = link.cid
        pb_link.Name = link.name
        pb_link.Tsize = link.size
        link_bytes = pb_link.SerializeToString()
        result += b"\x12" + _encode_varint(len(link_bytes)) + link_bytes

    # 2. Serialize Data after Links — field 1, wire type 2 = tag 0x0a
    if unixfs_data is not None:
        pb_unixfs = PBUnixFSData()
        pb_unixfs.Type = UnixFSData.TYPE_MAP[unixfs_data.type]  # type: ignore[assignment]
        # Only set fields with non-default values to match Kubo's encoding
        if unixfs_data.data:
            pb_unixfs.Data = unixfs_data.data
        if unixfs_data.filesize:
            pb_unixfs.filesize = unixfs_data.filesize
        for blocksize in unixfs_data.blocksizes:
            pb_unixfs.blocksizes.append(blocksize)
        if unixfs_data.hash_type:
            pb_unixfs.hashType = unixfs_data.hash_type
        if unixfs_data.fanout:
            pb_unixfs.fanout = unixfs_data.fanout
        data_bytes = pb_unixfs.SerializeToString()
        result += b"\x0a" + _encode_varint(len(data_bytes)) + data_bytes

    return result


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
        ...     print(f"Child CID: {format_cid_for_display(link.cid, max_len=16)}")

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


def create_leaf_node(data: bytes) -> bytes:
    """
    Create a DAG-PB leaf node for a single file chunk.

    Wraps raw bytes in UnixFS Data(type=File, data=chunk, filesize=len(chunk))
    inside a PBNode with no links. This matches Kubo's default behaviour
    (RawLeaves=false), ensuring leaf CIDs are byte-identical to those
    produced by `ipfs add`.

    Args:
        data: Raw chunk bytes (may be empty for an empty file)

    Returns:
        Encoded DAG-PB bytes, suitable for storage as a dag-pb block

    """
    unixfs_data = UnixFSData(type="file", data=data, filesize=len(data))
    return encode_dag_pb([], unixfs_data)


def balanced_layout(
    leaves: list[tuple[bytes, bytes, int]],
    max_links: int = MAX_LINKS_PER_NODE,
    put_block_callback: Callable[[bytes, bytes], None] | None = None,
) -> tuple[bytes, bytes]:
    """
    Build a balanced Merkle DAG from a flat list of leaf blocks.

    Groups leaves into batches of `max_links` (default 174), creates an
    internal DAG-PB node for each batch, then repeats level by level until
    a single root remains. Matches Go's balanced.Layout exactly.

    Args:
        leaves: List of (cid_bytes, block_bytes, file_data_size) tuples where
                - cid_bytes:      CID of the leaf block as raw bytes
                - block_bytes:    The encoded dag-pb leaf block bytes
                - file_data_size: Size of the raw file data inside this leaf
                                  (i.e. len(original chunk), NOT len(block))
        max_links: Max links per internal node (default 174, matches Kubo)
        put_block_callback: Optional async callback to store each internal node
                           Signature: callback(cid_bytes, block_bytes)

    Returns:
        (root_cid_bytes, root_block_bytes)

    Raises:
        ValueError: If leaves is empty

    """
    if not leaves:
        raise ValueError("Cannot build balanced layout from empty leaf list")

    if len(leaves) == 1:
        return leaves[0][0], leaves[0][1]

    # Each level entry: (cid_bytes, block_bytes, file_data_size, cumulative_block_size)
    # cumulative_block_size = len(this block) + sum(children's cumulative sizes)
    level: list[tuple[bytes, bytes, int, int]] = [
        (cid, blk, fsize, len(blk)) for cid, blk, fsize in leaves
    ]

    while len(level) > 1:
        next_level: list[tuple[bytes, bytes, int, int]] = []
        for i in range(0, len(level), max_links):
            batch = level[i : i + max_links]
            if len(batch) == 1:
                next_level.append(batch[0])
                continue

            # Build internal node: links to each child, UnixFS blocksizes
            internal_links: list[Link] = []
            blocksizes: list[int] = []
            total_filesize = 0
            total_cum = 0
            for cid_b, _, fsize, cum in batch:
                # Tsize = cumulative block size of the subtree rooted at this child
                internal_links.append(Link(cid=cid_b, name="", size=cum))
                blocksizes.append(fsize)
                total_filesize += fsize
                total_cum += cum

            unixfs_data = UnixFSData(
                type="file", filesize=total_filesize, blocksizes=blocksizes
            )
            internal_block = encode_dag_pb(internal_links, unixfs_data)
            internal_cid = compute_cid_v1(internal_block, codec=CODEC_DAG_PB)

            # Store internal node if callback provided
            if put_block_callback is not None:
                put_block_callback(internal_cid, internal_block)
            # cumulative size = own block + sum of children's cumulative sizes
            cum_size = len(internal_block) + total_cum
            next_level.append((internal_cid, internal_block, total_filesize, cum_size))
        level = next_level

    return level[0][0], level[0][1]
