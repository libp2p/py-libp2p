"""
Bitswap response sender for batching and sending messages.
"""

import logging
from typing import TYPE_CHECKING

from libp2p.abc import INetStream
from libp2p.peer.id import ID as PeerID

from .cid import CIDObject
from .messages import create_message

if TYPE_CHECKING:
    from .client import BitswapClient

logger = logging.getLogger(__name__)


class BitswapResponseSender:
    """Handles batching and sending of Bitswap responses."""

    def __init__(self, client: "BitswapClient"):
        self.client = client

    async def send_wantlist_responses_bg(
        self,
        peer_id: PeerID,
        peer_protocol: str,
        blocks_to_send_v100: list[bytes],
        blocks_to_send_v110: list[tuple[bytes, bytes]],
        presences_to_send: list[tuple[CIDObject, bool]],
    ) -> None:
        """Background task to send responses over a new outbound stream."""
        from libp2p.custom_types import TProtocol

        try:
            async with self.client._stream_limiter:
                outbound_stream = await self.client.host.new_stream(
                    peer_id, [TProtocol(peer_protocol)]
                )
        except Exception as e:
            logger.error(f"Failed to open outbound stream to send response: {e}")
            return

        try:
            await self.send_wantlist_responses_inline(
                outbound_stream,
                peer_id,
                blocks_to_send_v100,
                blocks_to_send_v110,
                presences_to_send,
            )
        except Exception as e:
            logger.error(f"Failed to send wantlist responses to {peer_id}: {e}")
        finally:
            await outbound_stream.close()

    async def send_wantlist_responses_inline(
        self,
        stream: INetStream,
        peer_id: PeerID,
        blocks_to_send_v100: list[bytes],
        blocks_to_send_v110: list[tuple[bytes, bytes]],
        presences_to_send: list[tuple[CIDObject, bool]],
    ) -> None:
        """Helper to send blocks on a specific stream."""
        if blocks_to_send_v100:
            await self.send_blocks_in_batches_v100(blocks_to_send_v100, peer_id, stream)
        if blocks_to_send_v110:
            await self.send_blocks_in_batches_v110(blocks_to_send_v110, peer_id, stream)
        if presences_to_send:
            presence_msg = create_message(block_presences=presences_to_send)
            await self.client._write_message(stream, presence_msg)

    async def send_blocks_in_batches_v100(
        self, blocks: list[bytes], peer_id: PeerID, stream: INetStream
    ) -> None:
        """Send blocks in batches to stay under message size limit."""
        MAX_BATCH_SIZE = 60000

        batch: list[bytes] = []
        batch_size = 0

        for block_data in blocks:
            block_size = len(block_data)

            if batch and (batch_size + block_size > MAX_BATCH_SIZE):
                msg = create_message(blocks_v100=batch)
                await self.client._write_message(stream, msg)
                logger.debug(f"Sent batch of {len(batch)} blocks to peer {peer_id}")
                batch = []
                batch_size = 0

            batch.append(block_data)
            batch_size += block_size

        if batch:
            msg = create_message(blocks_v100=batch)
            await self.client._write_message(stream, msg)
            logger.debug(f"Sent final batch of {len(batch)} blocks to peer {peer_id}")

    async def send_blocks_in_batches_v110(
        self,
        blocks: list[tuple[bytes, bytes]],
        peer_id: PeerID,
        stream: INetStream,
    ) -> None:
        """Send blocks (v1.1.0+ format) in batches to stay under message size limit."""
        MAX_BATCH_SIZE = 60000

        batch: list[tuple[bytes, bytes]] = []
        batch_size = 0

        for prefix, block_data in blocks:
            block_size = len(prefix) + len(block_data)

            if batch and (batch_size + block_size > MAX_BATCH_SIZE):
                msg = create_message(blocks_v110=batch)
                await self.client._write_message(stream, msg)
                logger.debug(f"Sent batch of {len(batch)} blocks to peer {peer_id}")
                batch = []
                batch_size = 0

            batch.append((prefix, block_data))
            batch_size += block_size

        if batch:
            msg = create_message(blocks_v110=batch)
            await self.client._write_message(stream, msg)
            logger.debug(f"Sent final batch of {len(batch)} blocks to peer {peer_id}")
