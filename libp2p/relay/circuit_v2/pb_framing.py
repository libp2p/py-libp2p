"""
Length-prefixed protobuf framing for circuit relay v2.

rust-libp2p uses ``quick_protobuf_codec::Codec`` (unsigned varint length + payload)
on hop/stop streams; raw ``SerializeToString()`` bytes are not compatible.
See ``protocols/relay`` in rust-libp2p (``MAX_MESSAGE_SIZE``).
"""

from libp2p.io.abc import (
    Reader,
    Writer,
)
from libp2p.utils.varint import (
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)

# protocols/relay/src/protocol.rs
MAX_CIRCUIT_V2_FRAME_PAYLOAD = 4096


async def write_circuit_v2_pb(stream: Writer, payload: bytes) -> None:
    if len(payload) > MAX_CIRCUIT_V2_FRAME_PAYLOAD:
        raise ValueError(
            f"circuit v2 protobuf frame ({len(payload)} bytes) exceeds max "
            f"{MAX_CIRCUIT_V2_FRAME_PAYLOAD}"
        )
    await stream.write(encode_varint_prefixed(payload))


async def read_circuit_v2_pb(stream: Reader) -> bytes:
    data = await read_varint_prefixed_bytes(stream)
    if len(data) > MAX_CIRCUIT_V2_FRAME_PAYLOAD:
        raise ValueError(
            f"circuit v2 protobuf frame ({len(data)} bytes) exceeds max "
            f"{MAX_CIRCUIT_V2_FRAME_PAYLOAD}"
        )
    return data
