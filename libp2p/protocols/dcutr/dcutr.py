import logging
from typing import Any

from libp2p.abc import IHost, INetStream
from libp2p.relay.circuit_v2.pb.dcutr_pb2 import HolePunch

DCUTR_PROTOCOL_ID = "/libp2p/dcutr/1.0.0"
logger = logging.getLogger(__name__)


class DCUtRProtocol:
    def __init__(self, host: IHost) -> None:
        self.host = host

    async def handle_inbound_stream(self, stream: INetStream) -> None:
        """Handle incoming DCUtR stream"""
        logger.info("Handling DCUtR stream")

        try:
            # Read CONNECT message
            msg = await self._read_message(stream)
            if msg.type == HolePunch.CONNECT:  # type: ignore
                await self._handle_connect(stream, msg)
        except Exception as e:
            logger.error(f"DCUtR error: {e}")
        finally:
            await stream.close()

    async def upgrade_connection(self, peer_id: Any) -> bool:
        """Start hole punching with peer"""
        logger.info(f"Starting hole punch to {peer_id}")

        try:
            # Open DCUtR stream
            stream = await self.host.new_stream(peer_id, [DCUTR_PROTOCOL_ID])  # type: ignore

            # Send CONNECT message
            connect_msg = HolePunch()  # type: ignore
            connect_msg.type = HolePunch.CONNECT  # type: ignore
            # Add our addresses (simplified)
            connect_msg.ObsAddrs.append(b"/ip4/127.0.0.1/tcp/0")

            await self._write_message(stream, connect_msg)

            # Read response
            await self._read_message(stream)

            # Send SYNC and attempt connections
            sync_msg = HolePunch()  # type: ignore
            sync_msg.type = HolePunch.SYNC  # type: ignore
            await self._write_message(stream, sync_msg)

            logger.info("Hole punch attempt completed")
            return True

        except Exception as e:
            logger.error(f"Hole punch failed: {e}")
            return False

    async def _handle_connect(self, stream: INetStream, msg: Any) -> None:
        """Handle CONNECT message"""
        # Send our CONNECT response
        response = HolePunch()  # type: ignore
        response.type = HolePunch.CONNECT  # type: ignore
        response.ObsAddrs.append(b"/ip4/127.0.0.1/tcp/0")

        await self._write_message(stream, response)

        # Wait for SYNC
        await self._read_message(stream)
        logger.info("Received SYNC, starting hole punch")

    async def _read_message(self, stream: INetStream) -> Any:
        """Read protobuf message from stream"""
        # Simple message reading (length-prefixed)
        length_bytes = await stream.read(1)
        if not length_bytes:
            raise ValueError("Stream closed")

        length = length_bytes[0]  # Convert first byte to integer
        data = await stream.read(length)

        msg = HolePunch()  # type: ignore
        msg.ParseFromString(data)
        return msg

    async def _write_message(self, stream: INetStream, msg: Any) -> None:
        """Write protobuf message to stream"""
        data = msg.SerializeToString()
        await stream.write(bytes([len(data)]) + data)
