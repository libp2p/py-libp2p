from typing import AsyncIterator, Callable, Awaitable, Optional
from libp2p.bitswap.cid import (
    parse_cid, cid_to_bytes,
    CODEC_DAG_PB, CODEC_DAG_JSON, CODEC_DAG_CBOR, CODEC_IPLD, CODEC_DAG_JOSE, _normalise_codec
)
from libp2p.bitswap.dag import decode_node, decode_dag_pb, get_codec_from_cid

async def walk_dag(root_cid_bytes: bytes, get_block: Callable[[bytes], Awaitable[Optional[bytes]]], recursive: bool = True) -> AsyncIterator[bytes]:
    queue = [root_cid_bytes]
    visited = set()
    while queue:
        curr_cid = queue.pop(0)
        if curr_cid in visited:
            continue
        visited.add(curr_cid)
        yield curr_cid
        
        if not recursive and curr_cid != root_cid_bytes:
            continue
            
        data = await get_block(curr_cid)
        if data is None:
            continue
            
        codec = get_codec_from_cid(curr_cid)
        norm_codec = _normalise_codec(codec)
        
        if norm_codec == CODEC_DAG_PB:
            try:
                node_links, _ = decode_dag_pb(data)
                for link in node_links:
                    if hasattr(link, "cid"):
                        queue.append(link.cid)
            except Exception:
                pass
        elif norm_codec in (CODEC_DAG_JSON, CODEC_DAG_CBOR, CODEC_IPLD, CODEC_DAG_JOSE):
            try:
                decoded = decode_node(data, codec)
                def extract_links(obj):
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
