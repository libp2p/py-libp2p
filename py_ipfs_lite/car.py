import io
from typing import Any

import trio
import varint
from cbor2 import CBORTag, dumps, loads
from libp2p.bitswap.cid import (
    _normalise_codec,
    cid_to_bytes,
    format_cid_for_display,
    parse_cid,
    parse_cid_codec,
)
from libp2p.bitswap.dag import decode_dag_pb

from py_ipfs_lite.dag_utils import decode_node


async def _read_exactly(f: Any, n: int) -> bytes:
    data = bytearray()
    while len(data) < n:
        chunk = await f.read(n - len(data))
        if not chunk:
            raise EOFError("Unexpected EOF")
        data.extend(chunk)
    return bytes(data)


async def _read_varint(f: Any) -> int:
    shift = 0
    result = 0
    while True:
        chunk = await f.read(1)
        if not chunk:
            if shift == 0:
                raise TypeError("EOF")
            raise EOFError("Unexpected EOF reading varint")
        val = chunk[0]
        result |= (val & 0x7F) << shift
        if not (val & 0x80):
            break
        shift += 7
    return result


def get_cid_len(data: bytes) -> int:
    if len(data) >= 34 and data[0] == 0x12 and data[1] == 0x20:
        return 34

    stream = io.BytesIO(data)
    _version = varint.decode_stream(stream)
    _codec = varint.decode_stream(stream)
    _mh_code = varint.decode_stream(stream)
    mh_len = varint.decode_stream(stream)
    stream.read(mh_len)
    return stream.tell()


async def export_car(peer: Any, cid_str: str, output_path: str) -> None:
    root_cid = parse_cid(cid_str)

    async with await trio.open_file(output_path, "wb") as f:
        # Header
        header_dict = {
            "version": 1,
            "roots": [CBORTag(42, b"\x00" + cid_to_bytes(root_cid))],
        }
        header_bytes = dumps(header_dict)
        await f.write(varint.encode(len(header_bytes)))
        await f.write(header_bytes)

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
                data = await peer.exchange().get_block(curr_cid_bytes)
                if data is None:
                    continue

            block_len = len(curr_cid_bytes) + len(data)
            await f.write(varint.encode(block_len))
            await f.write(curr_cid_bytes)
            await f.write(data)

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


async def import_car(peer: Any, input_path: str) -> list[str]:
    from cbor2 import CBORError

    from py_ipfs_lite.exceptions import CarParseError

    roots = []  # type: ignore[var-annotated]
    async with await trio.open_file(input_path, "rb") as f:
        # Header length
        try:
            header_len = await _read_varint(f)
        except TypeError:
            return roots

        try:
            header_bytes = await _read_exactly(f, header_len)
            header = loads(header_bytes)
            if header.get("version") != 1:
                raise CarParseError(f"Unsupported CAR version: {header.get('version')}")

            for root in header.get("roots", []):
                if isinstance(root, CBORTag) and root.tag == 42:
                    cid_bytes = root.value[1:]
                    cid = parse_cid(cid_bytes)
                    roots.append(format_cid_for_display(cid))

            # Read blocks
            while True:
                try:
                    block_len = await _read_varint(f)
                except TypeError:
                    break

                block_data_full = await _read_exactly(f, block_len)
                if not block_data_full:
                    break

                cid_len = get_cid_len(block_data_full)
                cid_bytes = block_data_full[:cid_len]
                data = block_data_full[cid_len:]

                # Verify block hash
                cid = parse_cid(cid_bytes)
                import multihash

                mh = multihash.decode(cid.multihash)
                try:
                    actual_mh = multihash.digest(data, mh.code, length=mh.length)
                    if actual_mh.digest != mh.digest:
                        raise ValueError(f"Hash mismatch for block {cid}")
                except Exception as e:
                    raise ValueError(f"Failed to verify block {cid}: {e}")

                await peer.blockstore.put(cid_bytes, data)

            for root in roots:
                if not await peer.has_block(root):
                    raise CarParseError(f"CAR file is missing root block {root}")
        except (CBORError, TypeError, IndexError, EOFError, ValueError) as e:
            raise CarParseError(f"Failed to parse CAR file: {e}") from e

    return roots
