import io
import varint
from typing import List
from cbor2 import loads, dumps, CBORTag

from libp2p.bitswap.cid import (
    parse_cid, cid_to_bytes, format_cid_for_display,
    CODEC_DAG_PB, CODEC_RAW, parse_cid_codec, _normalise_codec
)
from libp2p.bitswap.dag import MerkleDag, decode_dag_pb
from py_ipfs_lite.dag_utils import decode_node

def get_cid_len(data: bytes) -> int:
    if data[0] == 0x12 and data[1] == 0x20:
        return 34
    
    stream = io.BytesIO(data)
    _version = varint.decode_stream(stream)
    _codec = varint.decode_stream(stream)
    _mh_code = varint.decode_stream(stream)
    mh_len = varint.decode_stream(stream)
    stream.read(mh_len)
    return stream.tell()

async def export_car(peer, cid_str: str, output_path: str):
    root_cid = parse_cid(cid_str)
    
    with open(output_path, "wb") as f:
        # Header
        header_dict = {"version": 1, "roots": [CBORTag(42, b'\x00' + cid_to_bytes(root_cid))]}
        header_bytes = dumps(header_dict)
        f.write(varint.encode(len(header_bytes)))
        f.write(header_bytes)
        
        # Traverse
        queue = [cid_to_bytes(root_cid)]
        visited = set()
        
        while queue:
            curr_cid_bytes = queue.pop(0)
            if curr_cid_bytes in visited:
                continue
            visited.add(curr_cid_bytes)
            
            data = await peer.blockstore.get(curr_cid_bytes)
            if data is None:
                data = await peer.exchange.get_block(curr_cid_bytes)
                if data is None:
                    continue
                
            block_len = len(curr_cid_bytes) + len(data)
            f.write(varint.encode(block_len))
            f.write(curr_cid_bytes)
            f.write(data)
            
            codec = parse_cid_codec(curr_cid_bytes)
            norm_codec = _normalise_codec(codec)
            
            if str(norm_codec) == "dag-pb":
                try:
                    node_links, _ = decode_dag_pb(data)
                    for link in node_links:
                        if hasattr(link, "cid"):
                            queue.append(link.cid)
                except Exception:
                    pass
            elif str(norm_codec) in ("dag-json", "dag-cbor", "ipld", "dag-jose"):
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

async def import_car(peer, input_path: str) -> List[str]:
    roots = []
    with open(input_path, "rb") as f:
        # Header length
        try:
            header_len = varint.decode_stream(f)
        except TypeError:
            return roots
            
        header_bytes = f.read(header_len)
        header = loads(header_bytes)
        if header.get("version") != 1:
            raise ValueError(f"Unsupported CAR version: {header.get('version')}")
            
        for root in header.get("roots", []):
            if isinstance(root, CBORTag) and root.tag == 42:
                cid_bytes = root.value[1:]
                cid = parse_cid(cid_bytes)
                roots.append(format_cid_for_display(cid))
                
        # Read blocks
        while True:
            try:
                block_len = varint.decode_stream(f)
            except TypeError:
                break
                
            block_data_full = f.read(block_len)
            if not block_data_full:
                break
                
            cid_len = get_cid_len(block_data_full)
            cid_bytes = block_data_full[:cid_len]
            data = block_data_full[cid_len:]
            
            await peer.blockstore.put(cid_bytes, data)
            
    return roots
