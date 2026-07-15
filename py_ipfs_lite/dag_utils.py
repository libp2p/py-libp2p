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


async def walk_dag(
    root_cid_bytes: bytes,
    get_block: Callable[[bytes], Awaitable[bytes | None]],
    recursive: bool = True,
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
                pass
        elif str(norm_codec) in ("dag-json", "dag-cbor", "dag-jose", "ipld"):
            try:
                decoded = decode_node(data, codec)

                def extract_links(obj: Any) -> None:
                    if isinstance(obj, dict):
                        if "/" in obj and isinstance(obj["/"], (str, bytes)):
                            try:
                                link_cid = parse_cid(obj["/"])
                                queue.append(cid_to_bytes(link_cid))
                            except Exception:
                                pass
                        for v in obj.values():
                            extract_links(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            extract_links(item)

                extract_links(decoded)
            except Exception:
                pass
