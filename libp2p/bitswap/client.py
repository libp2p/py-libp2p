"""
Bitswap client implementation for block exchange.
Supports v1.0.0, v1.1.0, and v1.2.0 protocols.
"""

import logging
from typing import Any

import trio
import varint

from libp2p.abc import IHost, INetStream
from libp2p.peer.id import ID as PeerID

from .block_store import BlockStore, MemoryBlockStore
from .cid import (
    CID_V0,
    compute_cid,
    get_cid_prefix,
    reconstruct_cid_from_prefix_and_data,
    verify_cid,
)
from .config import (
    BITSWAP_PROTOCOL_V100,
    BITSWAP_PROTOCOL_V120,
    BITSWAP_PROTOCOLS,
    DEFAULT_PRIORITY,
    DEFAULT_TIMEOUT,
    MAX_BLOCK_SIZE,
    MAX_MESSAGE_SIZE,
)
from .errors import (
    BlockNotFoundError,
    BlockTooLargeError,
    MessageTooLargeError,
    TimeoutError as BitswapTimeoutError,
)
from .messages import create_message, create_wantlist_entry
from .pb.bitswap_pb2 import Message

logger = logging.getLogger(__name__)


class BitswapClient:
    """
    Bitswap client for exchanging blocks with other peers.

    Supports Bitswap protocol versions 1.0.0, 1.1.0, and 1.2.0 for content
    discovery and file sharing in a peer-to-peer network.
    """

    def __init__(
        self,
        host: IHost,
        block_store: BlockStore | None = None,
        protocol_version: str = BITSWAP_PROTOCOL_V120,
    ):
        """
        Initialize Bitswap client.

        Args:
            host: The libp2p host
            block_store: Block storage backend (defaults to in-memory)
            protocol_version: Preferred protocol version (defaults to v1.2.0)

        """
        self.host = host
        self.block_store = block_store or MemoryBlockStore()
        self.protocol_version = protocol_version
        self._wantlist: dict[
            bytes, dict[str, Any]
        ] = {}  # CID -> {priority, want_type, send_dont_have}
        self._peer_wantlists: dict[
            PeerID, dict[bytes, dict[str, Any]]
        ] = {}  # peer -> wantlist
        self._pending_requests: dict[bytes, trio.Event] = {}  # CID -> event
        self._peer_protocols: dict[PeerID, str] = {}  # peer -> negotiated protocol
        self._nursery: trio.Nursery | None = None
        self._started = False

    async def start(self) -> None:
        """Start the Bitswap client."""
        if self._started:
            return

        # Set stream handler for all supported Bitswap protocols
        for protocol in BITSWAP_PROTOCOLS:
            self.host.set_stream_handler(
                protocol,
                self._handle_stream,  # type: ignore[arg-type]
            )

        self._started = True
        logger.info(f"Bitswap client started (protocol: {self.protocol_version})")

    async def stop(self) -> None:
        """Stop the Bitswap client."""
        if not self._started:
            return

        self._started = False
        # Clear wantlists and pending requests
        self._wantlist.clear()
        self._peer_wantlists.clear()
        self._pending_requests.clear()
        self._peer_protocols.clear()
        logger.info("Bitswap client stopped")

    def set_nursery(self, nursery: trio.Nursery) -> None:
        """Set the nursery for background tasks."""
        self._nursery = nursery

    async def add_block(self, cid: bytes, data: bytes) -> None:
        """
        Add a block to the local store.

        Args:
            cid: The CID of the block
            data: The block data

        Raises:
            BlockTooLargeError: If the block exceeds maximum size

        """
        if len(data) > MAX_BLOCK_SIZE:
            raise BlockTooLargeError(
                f"Block size {len(data)} exceeds maximum {MAX_BLOCK_SIZE}"
            )

        await self.block_store.put_block(cid, data)
        logger.debug(f"Added block {cid.hex()[:16]}... to store")

        # Notify peers who wanted this block
        await self._notify_peers_about_block(cid, data)

    async def get_block(
        self,
        cid: bytes,
        peer_id: PeerID | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes:
        """
        Get a block, fetching from peers if not available locally.

        Args:
            cid: The CID of the block to fetch
            peer_id: Optional specific peer to request from
            timeout: Timeout in seconds

        Returns:
            The block data

        Raises:
            BlockNotFoundError: If the block cannot be found
            BitswapTimeoutError: If the request times out

        """
        # Check local store first
        data = await self.block_store.get_block(cid)
        if data is not None:
            return data

        # Request from network
        return await self._request_block(cid, peer_id, timeout)

    async def want_block(
        self,
        cid: bytes,
        priority: int = DEFAULT_PRIORITY,
        want_type: int = 0,  # 0 = Block, 1 = Have (v1.2.0)
        send_dont_have: bool = False,  # v1.2.0
    ) -> None:
        """
        Add a block to the wantlist without blocking.

        Args:
            cid: The CID of the block to want
            priority: Priority of the request
            want_type: 0 for Block (full block), 1 for Have (just check) - v1.2.0
            send_dont_have: Whether to request DontHave response if not found - v1.2.0

        """
        self._wantlist[cid] = {
            "priority": priority,
            "want_type": want_type,
            "send_dont_have": send_dont_have,
        }
        logger.debug(
            f"Added {cid.hex()[:16]}... to wantlist "
            f"(priority={priority}, type={'Have' if want_type else 'Block'})"
        )

    async def have_block(self, cid: bytes, peer_id: PeerID | None = None) -> bool:
        """
        Check if a peer has a block (v1.2.0 feature).

        Args:
            cid: The CID of the block to check
            peer_id: Optional specific peer to query

        Returns:
            True if peer has the block, False otherwise

        """
        # Add to wantlist with Have type
        await self.want_block(cid, want_type=1, send_dont_have=True)

        # Send wantlist to peer(s)
        if peer_id:
            await self._send_wantlist_to_peer(peer_id, [cid])
        else:
            await self._broadcast_wantlist([cid])

        # Wait for response (simplified - in production, track Have/DontHave responses)
        # For now, check if block appeared in store
        try:
            with trio.fail_after(5.0):
                while not await self.block_store.has_block(cid):
                    await trio.sleep(0.1)
            return True
        except trio.TooSlowError:
            return False
        finally:
            await self.cancel_want(cid)

    async def cancel_want(self, cid: bytes) -> None:
        """
        Cancel a previous want for a block.

        Args:
            cid: The CID to cancel

        """
        if cid in self._wantlist:
            del self._wantlist[cid]
            logger.debug(f"Removed {cid.hex()[:16]}... from wantlist")

            # Send cancel message to all peers
            await self._broadcast_cancel(cid)

    async def _request_block(
        self, cid: bytes, peer_id: PeerID | None, timeout: float
    ) -> bytes:
        """Request a block from the network."""
        # Add to wantlist
        await self.want_block(cid)

        # Create pending request event
        if cid not in self._pending_requests:
            self._pending_requests[cid] = trio.Event()

        # Send wantlist to peers
        if peer_id:
            await self._send_wantlist_to_peer(peer_id, [cid])
        else:
            await self._broadcast_wantlist([cid])

        # Wait for block to arrive
        try:
            with trio.fail_after(timeout):
                await self._pending_requests[cid].wait()

            # Get the block from store
            data = await self.block_store.get_block(cid)
            if data is None:
                raise BlockNotFoundError(f"Block {cid.hex()[:16]}... not found")

            return data
        except trio.TooSlowError:
            raise BitswapTimeoutError(f"Timeout waiting for block {cid.hex()[:16]}...")
        finally:
            # Cleanup
            await self.cancel_want(cid)
            if cid in self._pending_requests:
                del self._pending_requests[cid]

    async def _send_wantlist_to_peer(self, peer_id: PeerID, cids: list[bytes]) -> None:
        """Send wantlist to a specific peer."""
        try:
            # Create wantlist entries with full v1.2.0 information
            entries = []
            for cid in cids:
                want_info = self._wantlist.get(
                    cid,
                    {
                        "priority": DEFAULT_PRIORITY,
                        "want_type": 0,
                        "send_dont_have": False,
                    },
                )
                entry = create_wantlist_entry(
                    cid,
                    want_info["priority"],
                    cancel=False,
                    want_type=want_info.get("want_type", 0),
                    send_dont_have=want_info.get("send_dont_have", False),
                )
                entries.append(entry)

            # Create message
            msg = create_message(wantlist_entries=entries, full_wantlist=False)

            # Get negotiated protocol for this peer or use all protocols
            protocols = [self._peer_protocols.get(peer_id, self.protocol_version)]
            if peer_id not in self._peer_protocols:
                protocols = BITSWAP_PROTOCOLS  # Try all

            # Open stream and send message
            stream = await self.host.new_stream(
                peer_id,
                protocols,  # type: ignore[arg-type]
            )

            # Store negotiated protocol
            if hasattr(stream, "protocol"):
                self._peer_protocols[peer_id] = stream.protocol  # type: ignore[attr-defined]

            await self._write_message(stream, msg)
            logger.debug(f"Sent wantlist to peer {peer_id}")
        except Exception as e:
            logger.error(f"Failed to send wantlist to peer {peer_id}: {e}")

    async def _broadcast_wantlist(self, cids: list[bytes]) -> None:
        """Broadcast wantlist to all connected peers."""
        peers = self.host.get_network().connections.keys()
        for peer_id in peers:
            if self._nursery:
                self._nursery.start_soon(self._send_wantlist_to_peer, peer_id, cids)
            else:
                await self._send_wantlist_to_peer(peer_id, cids)

    async def _broadcast_cancel(self, cid: bytes) -> None:
        """Broadcast a cancel message to all peers."""
        entry = create_wantlist_entry(cid, cancel=True)
        msg = create_message(wantlist_entries=[entry])

        peers = self.host.get_network().connections.keys()
        for peer_id in peers:
            try:
                stream = await self.host.new_stream(
                    peer_id,
                    [BITSWAP_PROTOCOL_V100],  # type: ignore[list-item]
                )
                await self._write_message(stream, msg)
            except Exception as e:
                logger.debug(f"Failed to send cancel to peer {peer_id}: {e}")

    async def _notify_peers_about_block(self, cid: bytes, data: bytes) -> None:
        """Notify peers who wanted this block."""
        peers_to_notify = []

        # Find peers who want this block
        for peer_id, wantlist in self._peer_wantlists.items():
            if cid in wantlist:
                want_info = wantlist[cid]
                peers_to_notify.append((peer_id, want_info))

        # Send block or presence to interested peers
        for peer_id, want_info in peers_to_notify:
            try:
                # Get peer's protocol version
                peer_protocol = self._peer_protocols.get(peer_id, BITSWAP_PROTOCOL_V100)

                # Check if peer wants Have or Block
                want_type = want_info.get("want_type", 0)

                if want_type == 1:  # Have request (v1.2.0)
                    # Send BlockPresence (Have)
                    msg = create_message(block_presences=[(cid, True)])
                else:  # Block request
                    # Send the actual block
                    if peer_protocol == BITSWAP_PROTOCOL_V100:
                        # v1.0.0: use blocks field
                        msg = create_message(blocks_v100=[data])
                    else:
                        # v1.1.0+: use payload field with CID prefix
                        prefix = get_cid_prefix(cid)
                        msg = create_message(blocks_v110=[(prefix, data)])

                stream = await self.host.new_stream(
                    peer_id,
                    [peer_protocol],  # type: ignore[list-item]
                )
                await self._write_message(stream, msg)
                logger.debug(f"Sent block {cid.hex()[:16]}... to peer {peer_id}")
            except Exception as e:
                logger.error(f"Failed to send block to peer {peer_id}: {e}")

    async def _handle_stream(self, stream: INetStream) -> None:
        """Handle incoming Bitswap stream."""
        peer_id = stream.muxed_conn.peer_id
        logger.debug(f"Handling Bitswap stream from peer {peer_id}")

        try:
            while True:
                # Read message
                msg = await self._read_message(stream)
                if msg is None:
                    break

                # Process message
                await self._process_message(msg, peer_id, stream)

        except Exception as e:
            logger.error(f"Error handling stream from {peer_id}: {e}")
        finally:
            await stream.close()

    async def _process_message(
        self, msg: Message, peer_id: PeerID, stream: INetStream
    ) -> None:
        """Process a received Bitswap message."""
        # Detect peer protocol version from stream
        if hasattr(stream, "protocol"):
            self._peer_protocols[peer_id] = stream.protocol  # type: ignore[attr-defined]

        # Process wantlist
        if msg.HasField("wantlist"):
            await self._process_wantlist(msg.wantlist, peer_id, stream)

        # Process blocks (v1.0.0 format)
        if msg.blocks:
            await self._process_blocks_v100(msg.blocks)  # type: ignore[arg-type]

        # Process payload (v1.1.0+ format)
        if msg.payload:
            await self._process_blocks_v110(msg.payload)  # type: ignore[arg-type]

        # Process block presences (v1.2.0 format)
        if msg.blockPresences:
            await self._process_block_presences(msg.blockPresences)  # type: ignore[arg-type]

    async def _process_wantlist(
        self, wantlist: Message.Wantlist, peer_id: PeerID, stream: INetStream
    ) -> None:
        """Process a wantlist from a peer."""
        # Initialize peer wantlist if needed
        if peer_id not in self._peer_wantlists:
            self._peer_wantlists[peer_id] = {}

        peer_wantlist = self._peer_wantlists[peer_id]

        # Update based on full or incremental wantlist
        if wantlist.full:
            peer_wantlist.clear()

        # Get peer protocol for response format
        peer_protocol = self._peer_protocols.get(peer_id, BITSWAP_PROTOCOL_V100)

        # Process entries
        blocks_to_send_v100 = []  # For v1.0.0
        blocks_to_send_v110 = []  # For v1.1.0+
        presences_to_send = []  # For v1.2.0

        for entry in wantlist.entries:
            if entry.cancel:
                # Remove from peer's wantlist
                if entry.block in peer_wantlist:
                    del peer_wantlist[entry.block]
            else:
                # Add to peer's wantlist with full info (v1.2.0)
                peer_wantlist[entry.block] = {
                    "priority": entry.priority,
                    "want_type": entry.wantType,
                    "send_dont_have": entry.sendDontHave,
                }

                # Check if we have this block
                has_block = await self.block_store.has_block(entry.block)

                # Handle based on want type (v1.2.0)
                if entry.wantType == 1:  # Have request
                    # Send presence information
                    if has_block or entry.sendDontHave:
                        presences_to_send.append((entry.block, has_block))
                else:  # Block request
                    if has_block:
                        data = await self.block_store.get_block(entry.block)
                        if data:
                            if peer_protocol == BITSWAP_PROTOCOL_V100:
                                blocks_to_send_v100.append(data)
                            else:
                                prefix = get_cid_prefix(entry.block)
                                blocks_to_send_v110.append((prefix, data))
                    elif entry.sendDontHave:
                        # Send DontHave (v1.2.0)
                        presences_to_send.append((entry.block, False))

        # Send responses
        if blocks_to_send_v100 or blocks_to_send_v110 or presences_to_send:
            response_msg = create_message(
                blocks_v100=blocks_to_send_v100 if blocks_to_send_v100 else None,
                blocks_v110=blocks_to_send_v110 if blocks_to_send_v110 else None,
                block_presences=presences_to_send if presences_to_send else None,
            )
            await self._write_message(stream, response_msg)

            if blocks_to_send_v100 or blocks_to_send_v110:
                count = len(blocks_to_send_v100) + len(blocks_to_send_v110)
                logger.debug(f"Sent {count} blocks to peer {peer_id}")
            if presences_to_send:
                logger.debug(
                    f"Sent {len(presences_to_send)} block presences to peer {peer_id}"
                )

    async def _process_blocks_v100(self, blocks: list[bytes]) -> None:
        """Process received blocks (v1.0.0 format)."""
        for block_data in blocks:
            # For v1.0.0, compute CID from the block data
            cid = compute_cid(block_data, version=CID_V0)

            # Store the block
            await self.block_store.put_block(cid, block_data)
            logger.debug(f"Received and stored block {cid.hex()[:16]}... (v1.0.0)")

            # Notify pending requests
            if cid in self._pending_requests:
                self._pending_requests[cid].set()

    async def _process_blocks_v110(self, blocks: list[Any]) -> None:
        """Process received blocks (v1.1.0+ format with CID prefix)."""
        for block_msg in blocks:
            prefix = block_msg.prefix
            data = block_msg.data

            # Reconstruct CID from prefix and data
            cid = reconstruct_cid_from_prefix_and_data(prefix, data)

            # Verify CID matches data
            if not verify_cid(cid, data):
                logger.warning(f"CID verification failed for block {cid.hex()[:16]}...")
                continue

            # Store the block
            await self.block_store.put_block(cid, data)
            logger.debug(f"Received and stored block {cid.hex()[:16]}... (v1.1.0+)")

            # Notify pending requests
            if cid in self._pending_requests:
                self._pending_requests[cid].set()

    async def _process_block_presences(self, presences: list[Any]) -> None:
        """Process received block presences (v1.2.0)."""
        for presence in presences:
            cid = presence.cid
            has_block = presence.type == Message.Have

            logger.debug(
                f"Received presence for {cid.hex()[:16]}...: "
                f"{'Have' if has_block else 'DontHave'}"
            )

            # Could implement more sophisticated tracking here
            # For now, just log the information

    async def _read_message(self, stream: INetStream) -> Message | None:
        """Read a length-prefixed message from the stream."""
        try:
            # Read length prefix
            length_bytes = await stream.read(10)  # Max varint length
            if not length_bytes:
                return None

            # Decode length
            length, bytes_read = varint.decode_bytes(length_bytes)

            if length > MAX_MESSAGE_SIZE:
                raise MessageTooLargeError(
                    f"Message size {length} exceeds maximum {MAX_MESSAGE_SIZE}"
                )

            # Read message data (accounting for already read bytes)
            remaining = length
            msg_data = length_bytes[bytes_read:]
            remaining -= len(msg_data)

            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    break
                msg_data += chunk  # type: ignore[operator]
                remaining -= len(chunk)

            # Parse message
            msg = Message()
            msg.ParseFromString(msg_data)
            return msg

        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None

    async def _write_message(self, stream: INetStream, msg: Message) -> None:
        """Write a length-prefixed message to the stream."""
        # Serialize message
        msg_bytes = msg.SerializeToString()

        if len(msg_bytes) > MAX_MESSAGE_SIZE:
            raise MessageTooLargeError(
                f"Message size {len(msg_bytes)} exceeds maximum {MAX_MESSAGE_SIZE}"
            )

        # Write length prefix and message
        length_prefix = varint.encode(len(msg_bytes))
        await stream.write(length_prefix + msg_bytes)
