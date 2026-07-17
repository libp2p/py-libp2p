from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from libp2p.bitswap.cid import (
    CODEC_DAG_PB,
    _normalise_codec,
    cid_to_bytes,
    parse_cid,
    parse_cid_codec,
)
from libp2p.bitswap.dag import decode_dag_pb

from py_ipfs_lite.peer import decode_node


def extract_cids(obj: Any, strict_missing: bool = False) -> list[bytes]:
    """Recursively extract CIDs from a decoded IPLD node."""
    from cbor2 import CBORTag
    from libp2p.bitswap.cid import parse_cid

    cids = []

    def _extract(curr: Any) -> None:
        if isinstance(curr, dict):
            if "/" in curr and isinstance(curr["/"], (str, bytes)):
                try:
                    link_cid = parse_cid(curr["/"])
                    cids.append(cid_to_bytes(link_cid))
                except Exception:
                    if strict_missing:
                        raise
            for v in curr.values():
                _extract(v)
        elif isinstance(curr, list):
            for item in curr:
                _extract(item)
        elif isinstance(curr, CBORTag) and curr.tag == 42:
            try:
                # CBOR tag 42 contains bytes, with a leading \x00
                # byte for multibase identity
                cid_bytes = curr.value[1:]
                link_cid = parse_cid(cid_bytes)
                cids.append(cid_to_bytes(link_cid))
            except Exception:
                if strict_missing:
                    raise

    _extract(obj)
    return cids


async def walk_dag(
    root_cid_bytes: bytes,
    get_block: Callable[[bytes], Awaitable[bytes | None]],
    recursive: bool = True,
    strict_missing: bool = False,
) -> AsyncIterator[bytes]:
    queue = [root_cid_bytes]
    visited = set()
    while queue:
        curr_cid = queue.pop(0)
        if curr_cid in visited:
            continue
        visited.add(curr_cid)
        yield curr_cid

        if not recursive:
            continue

        data = await get_block(curr_cid)
        if data is None:
            if strict_missing:
                from libp2p.bitswap.cid import format_cid_for_display

                from py_ipfs_lite.exceptions import BlockNotFoundError

                cid_str = format_cid_for_display(parse_cid(curr_cid))
                raise BlockNotFoundError(f"Missing block: {cid_str}")
            continue

        codec = parse_cid_codec(curr_cid)
        norm_codec = _normalise_codec(codec)

        if norm_codec == CODEC_DAG_PB:
            try:
                node_links, _ = decode_dag_pb(data)
                for link in node_links:
                    if hasattr(link, "cid"):
                        queue.append(link.cid)
            except Exception:
                if strict_missing:
                    raise
                pass
        elif str(norm_codec) in ("dag-json", "dag-cbor", "dag-jose", "ipld"):
            try:
                decoded = decode_node(data, codec)
                for cid_bytes in extract_cids(decoded, strict_missing):
                    queue.append(cid_bytes)
            except Exception:
                if strict_missing:
                    raise
                pass
