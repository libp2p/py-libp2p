"""
Bitswap client implementation for block exchange.
Supports v1.0.0, v1.1.0, v1.2.0, and v1.3.0 protocols.
"""

from collections.abc import Sequence
import hashlib
import logging
from typing import Any

import trio
import varint

from libp2p.abc import IHost, INetStream
from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import PeerInfo  # noqa: F401

from .block_store import BlockStore, MemoryBlockStore
from .cid import (
    CIDInput,
    CIDObject,
    format_cid_for_display,
    get_cid_prefix,
    parse_cid,
    reconstruct_cid_from_prefix_and_data,
    verify_cid,
)
from .config import (
    BITSWAP_PROTOCOL_V100,
    BITSWAP_PROTOCOL_V120,
    BITSWAP_PROTOCOL_V130,
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
from .pb.bitswap_1_3_0_pb2 import Message as Message_1_3
from .pb.bitswap_pb2 import Message
from .provider_query import ProviderQueryManager

logger = logging.getLogger(__name__)


class BitswapClient:
    """
    Bitswap client for exchanging blocks with other peers.

    Supports Bitswap protocol versions 1.0.0, 1.1.0, 1.2.0, and 1.3.0 for
    content discovery and file sharing in a peer-to-peer network.

    For 1.3.0 payment support, pass a payment_client and payment_engine.
    """

    def __init__(
        self,
        host: IHost,
        block_store: BlockStore | None = None,
        protocol_version: str = BITSWAP_PROTOCOL_V120,
        provider_query_manager: ProviderQueryManager | None = None,
        payment_client: Any = None,   # BitswapPaymentClient_1_3 (optional)
        payment_engine: Any = None,   # PaymentGatedDecisionEngine (optional)
    ):
        """
        Initialize Bitswap client.

        Args:
            host: The libp2p host
            block_store: Block storage backend (defaults to in-memory)
            protocol_version: Preferred protocol version (defaults to v1.2.0)
            provider_query_manager: Optional ProviderQueryManager for automatic
                DHT-based provider discovery.  When supplied,
                ``get_block()`` will query the DHT for providers before
                broadcasting to all connected peers.
            payment_client: Optional BitswapPaymentClient_1_3 for client-side
                payment handling (auto-pays for blocks in 1.3.0 mode).
            payment_engine: Optional PaymentGatedDecisionEngine for server-side
                payment gating (gates block serving behind payment in 1.3.0 mode).

        """
        self.host = host
        self.block_store = block_store or MemoryBlockStore()
        self.protocol_version = protocol_version
        self.provider_query_manager: ProviderQueryManager | None = (
            provider_query_manager
        )
        # 1.3.0 payment components (optional)
        self.payment_client = payment_client
        self.payment_engine = payment_engine

        self._wantlist: dict[
            CIDObject, dict[str, Any]
        ] = {}  # CID -> {priority, want_type, send_dont_have}
        self._peer_wantlists: dict[
            PeerID, dict[CIDObject, dict[str, Any]]
        ] = {}  # peer -> wantlist
        self._pending_requests: dict[CIDObject, trio.Event] = {}  # CID -> event
        # CID -> peers who sent DontHave
        self._dont_have_responses: dict[CIDObject, set[PeerID]] = {}
        self._peer_protocols: dict[PeerID, str] = {}  # peer -> negotiated protocol
        self._expected_blocks: dict[
            PeerID, set[CIDObject]
        ] = {}  # peer -> expected CIDs
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
                self._handle_stream,
            )

        self._started = True
        logger.info(f"Bitswap client started (protocol: {self.protocol_version})")

    async def stop(self) -> None:
        """Stop the Bitswap client."""
        if not self._started:
            return

        self._started = False
        # Unregister stream handlers for all supported Bitswap protocols
        for protocol in BITSWAP_PROTOCOLS:
            self.host.remove_stream_handler(protocol)
        # Clear wantlists and pending requests
        self._wantlist.clear()
        self._peer_wantlists.clear()
        self._pending_requests.clear()
        self._dont_have_responses.clear()
        self._peer_protocols.clear()
        self._expected_blocks.clear()
        logger.info("Bitswap client stopped")

    def set_nursery(self, nursery: trio.Nursery) -> None:
        """Set the nursery for background tasks."""
        self._nursery = nursery

    async def add_block(self, cid: CIDInput, data: bytes) -> None:
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

        cid_obj = parse_cid(cid)

        await self.block_store.put_block(cid_obj, data)
        logger.debug(
            f"Added block {format_cid_for_display(cid_obj, max_len=16)} to store"
        )

        # Notify peers who wanted this block
        await self._notify_peers_about_block(cid_obj, data)

    async def get_blocks_batch(
        self,
        cids: list[CIDInput],
        peer_id: PeerID | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        batch_size: int = 32,
    ) -> dict[bytes, bytes]:
        """
        Fetch multiple blocks in batches using a single wantlist per batch.

        Sends all CIDs in one wantlist message, waits for all responses on the
        same stream. This avoids opening hundreds of individual streams which
        causes Kubo to send GO_AWAY.

        Args:
            cids: List of CIDs to fetch
            peer_id: Optional specific peer to request from
            timeout: Timeout per batch in seconds
            batch_size: How many CIDs to request per wantlist message

        Returns:
            Dict mapping cid_bytes -> block_data for all successfully fetched blocks

        """
        results: dict[bytes, bytes] = {}
        cid_objs = [parse_cid(c) for c in cids]

        # Check local store first
        remaining: list[CIDObject] = []
        for cid_obj in cid_objs:
            data = await self.block_store.get_block(cid_obj)
            if data is not None:
                results[cid_obj.buffer] = data
            else:
                remaining.append(cid_obj)

        if not remaining:
            return results

        # Process in batches to avoid overwhelming the peer
        for batch_start in range(0, len(remaining), batch_size):
            batch = remaining[batch_start : batch_start + batch_size]

            # Register pending events for all CIDs in batch
            for cid_obj in batch:
                if cid_obj not in self._pending_requests:
                    self._pending_requests[cid_obj] = trio.Event()
                await self.want_block(cid_obj, send_dont_have=True)

            # Send all CIDs in a single wantlist to the peer
            if peer_id:
                await self._send_wantlist_to_peer(peer_id, batch)
            else:
                await self._broadcast_wantlist(batch)

            # Wait for all blocks in this batch
            try:
                with trio.fail_after(timeout):
                    for cid_obj in batch:
                        if cid_obj in self._pending_requests:
                            await self._pending_requests[cid_obj].wait()
            except trio.TooSlowError:
                msg = f"Batch timeout: {len(batch)} blocks, got partial results"
                logger.warning(msg)

            # Collect results and clean up
            for cid_obj in batch:
                data = await self.block_store.get_block(cid_obj)
                if data is not None:
                    results[cid_obj.buffer] = data
                else:
                    # Block may have arrived late (e.g. after payment round-trip).
                    # Check if the pending event was set after the timeout fired.
                    event = self._pending_requests.get(cid_obj)
                    if event and event.is_set():
                        data = await self.block_store.get_block(cid_obj)
                        if data is not None:
                            results[cid_obj.buffer] = data
                            logger.info(
                                f"Late block received (post-timeout): "
                                f"{format_cid_for_display(cid_obj)}"
                            )
                        else:
                            cid_str = format_cid_for_display(cid_obj)
                            logger.warning(f"Block not received: {cid_str}")
                    else:
                        cid_str = format_cid_for_display(cid_obj)
                        logger.warning(f"Block not received: {cid_str}")

                # Cleanup
                if cid_obj in self._pending_requests:
                    del self._pending_requests[cid_obj]
                if cid_obj in self._wantlist:
                    del self._wantlist[cid_obj]

        return results

    async def get_block(
        self,
        cid: CIDInput,
        peer_id: PeerID | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes:
        """
        Get a block, fetching from peers if not available locally.

        If a ``ProviderQueryManager`` was supplied at construction time and no
        explicit ``peer_id`` is given, the manager is consulted first to
        discover which peers have the block via the DHT.  The first discovered
        provider is used; if none is found the request falls back to
        broadcasting to all connected peers.

        Args:
            cid: The CID of the block to fetch
            peer_id: Optional peer to request from; DHT discovery is skipped when set.
            timeout: Timeout in seconds

        Returns:
            The block data

        Raises:
            BlockNotFoundError: If the block cannot be found
            BitswapTimeoutError: If the request times out

        """
        cid_obj = parse_cid(cid)

        # 1. Check local store first
        data = await self.block_store.get_block(cid_obj)
        if data is not None:
            return data

        # 2. If no explicit peer given, try DHT provider discovery
        if peer_id is None and self.provider_query_manager is not None:
            try:
                providers = await self.provider_query_manager.find_providers_single(
                    cid, timeout=min(5.0, timeout / 2)
                )
                if providers:
                    peer_id = providers[0]
                    logger.debug(
                        "DHT discovered provider %s for %s",
                        peer_id,
                        format_cid_for_display(cid_obj, max_len=12),
                    )
            except Exception as exc:
                logger.debug(
                    "Provider query failed, falling back to broadcast: %s",
                    exc,
                )

        # 3. Request from network (specific peer or broadcast)
        return await self._request_block(cid_obj, peer_id, timeout)

    async def want_block(
        self,
        cid: CIDInput,
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
        cid_obj = parse_cid(cid)

        self._wantlist[cid_obj] = {
            "priority": priority,
            "want_type": want_type,
            "send_dont_have": send_dont_have,
        }
        logger.debug(
            f"Added {format_cid_for_display(cid_obj, max_len=16)} to wantlist "
            f"(priority={priority}, type={'Have' if want_type else 'Block'})"
        )

    async def have_block(self, cid: CIDInput, peer_id: PeerID | None = None) -> bool:
        """
        Check if a peer has a block (v1.2.0 feature).

        Args:
            cid: The CID of the block to check
            peer_id: Optional specific peer to query

        Returns:
            True if peer has the block, False otherwise

        """
        cid_obj = parse_cid(cid)

        # Add to wantlist with Have type
        await self.want_block(cid_obj, want_type=1, send_dont_have=True)

        # Send wantlist to peer(s)
        if peer_id:
            await self._send_wantlist_to_peer(peer_id, [cid_obj])
        else:
            await self._broadcast_wantlist([cid_obj])

        # Wait for response (simplified - in production, track Have/DontHave responses)
        # For now, check if block appeared in store
        result = False
        try:
            with trio.fail_after(5.0):
                while not await self.block_store.has_block(cid_obj):
                    await trio.sleep(0.1)
            result = True
        except trio.TooSlowError:
            result = False
        finally:
            await self.cancel_want(cid_obj)

        return result

    async def cancel_want(self, cid: CIDInput) -> None:
        """
        Cancel a previous want for a block.

        Args:
            cid: The CID to cancel

        """
        cid_obj = parse_cid(cid)

        if cid_obj in self._wantlist:
            del self._wantlist[cid_obj]
            logger.debug(
                f"Removed {format_cid_for_display(cid_obj, max_len=16)} from wantlist"
            )

            # Send cancel message to all peers
            await self._broadcast_cancel(cid_obj)

    async def _request_block(
        self, cid: CIDObject, peer_id: PeerID | None, timeout: float
    ) -> bytes:
        """Request a block from the network."""
        logger.info(f"📤 Requesting block: {format_cid_for_display(cid)}")

        # Add to wantlist with sendDontHave=True for v1.2.0
        await self.want_block(cid, send_dont_have=True)

        # Create pending request event
        if cid not in self._pending_requests:
            self._pending_requests[cid] = trio.Event()

        # Send wantlist to peers
        if peer_id:
            await self._send_wantlist_to_peer(peer_id, [cid])
        else:
            await self._broadcast_wantlist([cid])

        # Wait for block to arrive
        result: bytes | None = None
        error: Exception | None = None

        try:
            logger.info(f"  ⏳ Waiting for block (timeout: {timeout}s)...")
            with trio.fail_after(timeout):
                await self._pending_requests[cid].wait()

            # Get the block from store
            data = await self.block_store.get_block(cid)
            if data is None:
                error = BlockNotFoundError(
                    f"Block {format_cid_for_display(cid, max_len=16)} not found"
                )
            else:
                result = data
                logger.info(f"  ✓ Block received! Size: {len(data)} bytes")
        except trio.TooSlowError as e:
            logger.error(f"  ✗ TIMEOUT waiting for block {format_cid_for_display(cid)}")
            error = BitswapTimeoutError(
                f"Timeout waiting for block {format_cid_for_display(cid, max_len=16)}"
            )
            error.__cause__ = e
        finally:
            # Cleanup
            await self.cancel_want(cid)
            if cid in self._pending_requests:
                del self._pending_requests[cid]
            if cid in self._dont_have_responses:
                del self._dont_have_responses[cid]

        if error:
            raise error
        assert result is not None
        return result

    async def _send_wantlist_to_peer(
        self, peer_id: PeerID, cids: list[CIDObject]
    ) -> None:
        """Send wantlist to a specific peer."""
        # Track expected blocks for this peer
        if peer_id not in self._expected_blocks:
            self._expected_blocks[peer_id] = set()

        peer_id_str = str(peer_id)
        logger.info(
            f"Adding {len(cids)} CIDs to expected_blocks for peer {peer_id_str}"
        )
        for cid in cids:
            logger.info(f"  + {format_cid_for_display(cid)}")

        self._expected_blocks[peer_id].update(cids)

        logger.info(
            f"Total expected blocks from {peer_id_str}: "
            f"{len(self._expected_blocks[peer_id])}"
        )

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
            if peer_id in self._peer_protocols:
                protocols = [TProtocol(self._peer_protocols[peer_id])]
            else:
                protocols = list(BITSWAP_PROTOCOLS)  # Try all

            # Open stream and send message
            stream = await self.host.new_stream(
                peer_id,
                protocols,
            )

            # Store negotiated protocol
            protocol = stream.get_protocol()
            if protocol:
                self._peer_protocols[peer_id] = str(protocol)

            await self._write_message(stream, msg)
            logger.debug(f"Sent wantlist to peer {peer_id}")

            # Keep stream open and read responses
            # This allows the provider to send blocks back on the same stream
            if self._nursery:
                self._nursery.start_soon(
                    self._read_responses_from_stream, stream, peer_id
                )
            else:
                await self._read_responses_from_stream(stream, peer_id)

        except Exception as e:
            logger.error(f"Failed to send wantlist to peer {peer_id}: {e}")

    async def _broadcast_wantlist(self, cids: list[CIDObject]) -> None:
        """Broadcast wantlist to all connected peers."""
        peers = self.host.get_network().connections.keys()
        for peer_id in peers:
            if self._nursery:
                self._nursery.start_soon(self._send_wantlist_to_peer, peer_id, cids)
            else:
                await self._send_wantlist_to_peer(peer_id, cids)

    async def _broadcast_cancel(self, cid: CIDObject) -> None:
        """Broadcast a cancel message to all peers."""
        entry = create_wantlist_entry(cid, cancel=True)
        msg = create_message(wantlist_entries=[entry])

        peers = self.host.get_network().connections.keys()
        for peer_id in peers:
            try:
                stream = await self.host.new_stream(
                    peer_id,
                    [BITSWAP_PROTOCOL_V100],
                )
                await self._write_message(stream, msg)
            except Exception as e:
                logger.debug(f"Failed to send cancel to peer {peer_id}: {e}")

    async def _notify_peers_about_block(self, cid: CIDObject, data: bytes) -> None:
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
                    [TProtocol(peer_protocol)],
                )
                await self._write_message(stream, msg)
                logger.debug(
                    f"Sent block {format_cid_for_display(cid, max_len=16)} "
                    f"to peer {peer_id}"
                )
            except Exception as e:
                logger.error(f"Failed to send block to peer {peer_id}: {e}")

    async def _read_responses_from_stream(
        self, stream: INetStream, peer_id: PeerID
    ) -> None:
        """
        Read responses from a stream after sending a wantlist.

        This keeps the stream open so the provider can send blocks back.
        Stops reading once all expected blocks are received.
        """
        try:
            peer_id_str = str(peer_id)
            logger.info(f"📡 Reading responses from {peer_id_str} on stream")
            message_count = 0

            while True:
                # Check if we've received all expected blocks from this peer
                if peer_id in self._expected_blocks:
                    remaining = len(self._expected_blocks[peer_id])
                    if remaining == 0:
                        logger.info(
                            f"✓ All expected blocks received from "
                            f"{peer_id_str}, closing stream"
                        )
                        break
                    else:
                        logger.debug(
                            f"Still expecting {remaining} blocks from {peer_id_str}"
                        )

                # Read message from provider WITHOUT timeout
                # We rely on expected_blocks tracking to know when to stop
                logger.debug(f"Waiting for message from {peer_id_str}...")
                msg = await self._read_message(stream)
                if msg is None:
                    logger.warning(f"Stream from {peer_id_str} closed by remote")
                    break

                message_count += 1
                logger.info(f"📨 Received message #{message_count} from {peer_id_str}")

                # Process the response (blocks, presences, etc.)
                await self._process_message(msg, peer_id, stream)

        except Exception as e:
            peer_id_str = str(peer_id)
            logger.error(f"Stream from {peer_id_str} ended with error: {e}")
            import traceback

            logger.error(traceback.format_exc())
        finally:
            # Clean up expected blocks for this peer
            if peer_id in self._expected_blocks:
                peer_id_str = str(peer_id)
                remaining = len(self._expected_blocks[peer_id])
                if remaining > 0:
                    logger.error("")
                    logger.error("=" * 70)
                    logger.error("⚠️  STREAM CLOSED WITH MISSING BLOCKS")
                    logger.error("=" * 70)
                    logger.error(f"Peer: {peer_id_str}")
                    logger.error(f"Missing {remaining} blocks:")
                    for i, cid in enumerate(self._expected_blocks[peer_id]):
                        logger.error(f"  {i + 1}. {format_cid_for_display(cid)}")
                    logger.error("=" * 70)
                    logger.error("")
                del self._expected_blocks[peer_id]
            try:
                await stream.close()
            except Exception as e:
                # Stream might already be closed
                logger.debug(f"Error closing stream: {e}")

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
        peer_id_str = str(peer_id)[:16]
        if msg.HasField("wantlist"):
            logger.warning("=" * 70)
            logger.warning(f"📥 RECEIVED WANTLIST from peer {peer_id_str}")
            logger.warning(f"   Entries: {len(msg.wantlist.entries)}")
            logger.warning(f"   Full: {msg.wantlist.full}")
            logger.warning("=" * 70)
            print(f"\n📥 RECEIVED WANTLIST from peer {peer_id_str} with {len(msg.wantlist.entries)} entries", flush=True)
        
        # Detect peer protocol version from stream
        protocol = stream.get_protocol()
        if protocol:
            self._peer_protocols[peer_id] = str(protocol)

        peer_protocol = str(protocol) if protocol else BITSWAP_PROTOCOL_V100

        # ── Bitswap 1.3.0 payment message handling ───────────────────────
        if peer_protocol == str(BITSWAP_PROTOCOL_V130):
            # Re-parse as 1.3.0 message to access payment fields
            msg_1_3 = Message_1_3()
            try:
                msg_1_3.ParseFromString(msg.SerializeToString())
            except Exception:
                msg_1_3 = None

            if msg_1_3 is not None:
                # Client-side: handle PaymentTerms / PaymentReceipts / PaymentRejections
                if self.payment_client and (
                    msg_1_3.payment_terms
                    or msg_1_3.payment_receipts
                    or msg_1_3.payment_rejections
                ):
                    response = await self.payment_client.process_incoming_message(
                        str(peer_id), msg_1_3
                    )
                    if response is not None:
                        await self._write_message_bytes(
                            stream, response.SerializeToString()
                        )

                # Process any blocks delivered alongside a payment receipt
                if msg_1_3.payload:
                    await self._process_blocks_v110(msg_1_3.payload)
                if msg_1_3.blocks:
                    await self._process_blocks_v100(list(msg_1_3.blocks), peer_id)

                # Server-side: handle PaymentAuthorizations
                if self.payment_engine and msg_1_3.payment_authorizations:
                    response = await self.payment_engine.process_incoming_1_3_message(
                        str(peer_id), msg_1_3
                    )
                    if response is not None:
                        await self._write_message_bytes(
                            stream, response.SerializeToString()
                        )

                # Handle PaymentRequired block presences specially
                if msg_1_3.blockPresences:
                    await self._process_block_presences_1_3(
                        msg_1_3.blockPresences, peer_id
                    )
                    # Don't fall through to normal presence processing
                    # (already handled above)
                    if msg.HasField("wantlist"):
                        await self._process_wantlist(msg.wantlist, peer_id, stream)
                    if msg.blocks:
                        await self._process_blocks_v100(list(msg.blocks), peer_id)
                    if msg.payload:
                        await self._process_blocks_v110(msg.payload)
                    return

        # ── Standard 1.0.0–1.2.0 message handling ────────────────────────
        # Process wantlist
        if msg.HasField("wantlist"):
            await self._process_wantlist(msg.wantlist, peer_id, stream)

        # Process blocks (v1.0.0 format)
        if msg.blocks:
            await self._process_blocks_v100(list(msg.blocks), peer_id)

        # Process payload (v1.1.0+ format)
        if msg.payload:
            await self._process_blocks_v110(msg.payload)

        # Process block presences (v1.2.0 format)
        if msg.blockPresences:
            await self._process_block_presences(msg.blockPresences, peer_id)

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

        # ── 1.3.0 payment-gated wantlist handling ──────────────────────────
        if str(peer_protocol) == str(BITSWAP_PROTOCOL_V130) and self.payment_engine:
            for entry in wantlist.entries:
                entry_cid = parse_cid(entry.block)
                if entry.cancel:
                    if entry_cid in peer_wantlist:
                        del peer_wantlist[entry_cid]
                    continue

                peer_wantlist[entry_cid] = {
                    "priority": entry.priority,
                    "want_type": entry.wantType,
                    "send_dont_have": entry.sendDontHave,
                }

                response_msg = await self.payment_engine.handle_want(
                    peer_id=str(peer_id),
                    cid=entry.block,
                    want_type=entry.wantType,
                    send_dont_have=entry.sendDontHave,
                    peer_protocol=str(BITSWAP_PROTOCOL_V130),
                )
                if response_msg is not None:
                    await self._write_message_bytes(
                        stream, response_msg.SerializeToString()
                    )
            return

        # ── Standard 1.0.0–1.2.0 wantlist handling ────────────────────────
        # Process entries
        blocks_to_send_v100 = []  # For v1.0.0
        blocks_to_send_v110 = []  # For v1.1.0+
        presences_to_send = []  # For v1.2.0

        for entry in wantlist.entries:
            entry_cid = parse_cid(entry.block)
            if entry.cancel:
                # Remove from peer's wantlist
                if entry_cid in peer_wantlist:
                    del peer_wantlist[entry_cid]
            else:
                # Add to peer's wantlist with full info (v1.2.0)
                peer_wantlist[entry_cid] = {
                    "priority": entry.priority,
                    "want_type": entry.wantType,
                    "send_dont_have": entry.sendDontHave,
                }

                # Check if we have this block
                has_block = await self.block_store.has_block(entry_cid)

                # Handle based on want type (v1.2.0)
                if entry.wantType == 1:  # Have request
                    # Send presence information
                    if has_block or entry.sendDontHave:
                        presences_to_send.append((entry_cid, has_block))
                else:  # Block request
                    if has_block:
                        data = await self.block_store.get_block(entry_cid)
                        if data:
                            if peer_protocol == BITSWAP_PROTOCOL_V100:
                                blocks_to_send_v100.append(data)
                            else:
                                prefix = get_cid_prefix(entry_cid)
                                blocks_to_send_v110.append((prefix, data))
                    elif entry.sendDontHave:
                        # Send DontHave (v1.2.0)
                        presences_to_send.append((entry_cid, False))

        # Send responses in batches to stay under MAX_MESSAGE_SIZE
        # and Noise protocol limit (65535 bytes)
        if blocks_to_send_v100 or blocks_to_send_v110 or presences_to_send:
            # Send blocks in batches
            if blocks_to_send_v100:
                await self._send_blocks_in_batches_v100(
                    blocks_to_send_v100, peer_id, stream
                )
            if blocks_to_send_v110:
                await self._send_blocks_in_batches_v110(
                    blocks_to_send_v110, peer_id, stream
                )
            # Send presences (usually small, can send all at once)
            if presences_to_send:
                presence_msg = create_message(block_presences=presences_to_send)
                await self._write_message(stream, presence_msg)
                logger.debug(
                    f"Sent {len(presences_to_send)} block presences to peer {peer_id}"
                )

    async def _send_blocks_in_batches_v100(
        self, blocks: list[bytes], peer_id: PeerID, stream: INetStream
    ) -> None:
        """Send blocks in batches to stay under message size limit."""
        # Noise protocol limit is 65535 bytes per message
        # Reserve some space for protobuf overhead
        MAX_BATCH_SIZE = 60000  # ~60KB per message for safety

        batch: list[bytes] = []
        batch_size = 0

        for block_data in blocks:
            block_size = len(block_data)

            # If adding this block would exceed limit, send current batch first
            if batch and (batch_size + block_size > MAX_BATCH_SIZE):
                msg = create_message(blocks_v100=batch)
                await self._write_message(stream, msg)
                logger.debug(f"Sent batch of {len(batch)} blocks to peer {peer_id}")
                batch = []
                batch_size = 0

            batch.append(block_data)
            batch_size += block_size

        # Send remaining blocks
        if batch:
            msg = create_message(blocks_v100=batch)
            await self._write_message(stream, msg)
            logger.debug(f"Sent final batch of {len(batch)} blocks to peer {peer_id}")

    async def _send_blocks_in_batches_v110(
        self,
        blocks: list[tuple[bytes, bytes]],
        peer_id: PeerID,
        stream: INetStream,
    ) -> None:
        """Send blocks (v1.1.0+ format) in batches to stay under message size limit."""
        # Noise protocol limit is 65535 bytes per message
        # Reserve some space for protobuf overhead
        MAX_BATCH_SIZE = 60000  # ~60KB per message for safety

        batch: list[tuple[bytes, bytes]] = []
        batch_size = 0

        for prefix, block_data in blocks:
            block_size = len(prefix) + len(block_data)

            # If adding this block would exceed limit, send current batch first
            if batch and (batch_size + block_size > MAX_BATCH_SIZE):
                msg = create_message(blocks_v110=batch)
                await self._write_message(stream, msg)
                logger.debug(f"Sent batch of {len(batch)} blocks to peer {peer_id}")
                batch = []
                batch_size = 0

            batch.append((prefix, block_data))
            batch_size += block_size

        # Send remaining blocks
        if batch:
            msg = create_message(blocks_v110=batch)
            await self._write_message(stream, msg)
            logger.debug(f"Sent final batch of {len(batch)} blocks to peer {peer_id}")

    async def _process_blocks_v100(self, blocks: list[bytes], peer_id: PeerID) -> None:
        """
        Process received blocks (v1.0.0 format).

        For v1.0.0, we can't reliably recompute CIDs from block data alone
        because we don't know which codec was used. Instead, we verify the
        block data against the CIDs we're expecting.
        """
        peer_id_str = str(peer_id)[:16] if hasattr(peer_id, "__str__") else "unknown"
        logger.info("=" * 70)
        logger.info(f"Processing {len(blocks)} blocks (v1.0.0) from peer {peer_id_str}")

        # Get the CIDs we're expecting from this peer
        expected_cids = self._expected_blocks.get(peer_id, set()).copy()
        logger.info(f"Expected {len(expected_cids)} blocks from this peer")
        logger.info("Expected CIDs:")
        for i, cid in enumerate(expected_cids):
            logger.info(f"  {i + 1}. {format_cid_for_display(cid)}")
        logger.info("=" * 70)

        for idx, block_data in enumerate(blocks):
            block_hash = hashlib.sha256(block_data).hexdigest()
            logger.info("")
            logger.info(f"Block {idx + 1}/{len(blocks)}:")
            logger.info(f"  Size: {len(block_data)} bytes")
            logger.info(f"  SHA-256: {block_hash}")
            logger.info(f"  First 64 bytes: {block_data[:64].hex()}")

            # Find which expected CID matches this block data
            matched_cid = None
            logger.info(f"  Checking against {len(expected_cids)} expected CIDs...")
            for i, cid in enumerate(expected_cids):
                logger.info(
                    f"    Attempt {i + 1}: Checking CID {format_cid_for_display(cid)}"
                )
                if verify_cid(cid, block_data):
                    matched_cid = cid
                    logger.info(
                        f"  ✓ MATCHED CID: {format_cid_for_display(matched_cid)}"
                    )
                    break
                else:
                    logger.info("    -> No match")

            if matched_cid:
                # Store the block with the correct CID
                await self.block_store.put_block(matched_cid, block_data)
                logger.info("  ✓ Stored successfully")

                # Remove from expected blocks for all peers
                for pid in self._expected_blocks:
                    if matched_cid in self._expected_blocks[pid]:
                        self._expected_blocks[pid].discard(matched_cid)
                        pid_str = (
                            str(pid)[:16] if hasattr(pid, "__str__") else "unknown"
                        )
                        logger.info(
                            f"  ✓ Removed from expected blocks for peer {pid_str}"
                        )

                # Notify pending requests
                if matched_cid in self._pending_requests:
                    logger.info("  ✓ Notifying pending request")
                    self._pending_requests[matched_cid].set()
            else:
                logger.error("  ✗ NO MATCH FOUND!")
                logger.error("  Block doesn't match any expected CID")
                logger.error(f"  Expected CIDs ({len(expected_cids)}):")
                for i, cid in enumerate(list(expected_cids)[:5]):
                    logger.error(f"    {i + 1}. {format_cid_for_display(cid)}")
                if len(expected_cids) > 5:
                    logger.error(f"    ... and {len(expected_cids) - 5} more")

        logger.info("")
        logger.info("=" * 70)
        logger.info("Block processing complete. Remaining expected blocks:")
        remaining = self._expected_blocks.get(peer_id, set())
        if remaining:
            logger.warning(f"  Still waiting for {len(remaining)} blocks:")
            for i, cid in enumerate(remaining):
                logger.warning(f"    {i + 1}. {format_cid_for_display(cid)}")
        else:
            logger.info("  ✓ All blocks received from this peer!")
        logger.info("=" * 70)

    async def _process_blocks_v110(self, blocks: Sequence[Any]) -> None:
        """Process received blocks (v1.1.0+ format with prefix)."""
        logger.debug(f"Processing {len(blocks)} blocks (v1.1.0+)")
        for block in blocks:
            prefix = block.prefix
            data = block.data

            # Decode CID from prefix and data, then convert to CID object
            cid_bytes = reconstruct_cid_from_prefix_and_data(prefix, data)
            cid = parse_cid(cid_bytes)

            # Store the block
            await self.block_store.put_block(cid, data)
            logger.debug(
                f"Received and stored block {format_cid_for_display(cid, max_len=16)} "
                f"(v1.1.0+)"
            )

            # Remove from expected blocks for all peers
            for peer_id in self._expected_blocks:
                self._expected_blocks[peer_id].discard(cid)

            # Notify pending requests
            if cid in self._pending_requests:
                logger.debug(
                    f"Notifying pending request for "
                    f"{format_cid_for_display(cid, max_len=16)}..."
                )
                self._pending_requests[cid].set()
            else:
                logger.debug(
                    f"No pending request for "
                    f"{format_cid_for_display(cid, max_len=16)}..."
                )

    async def _process_block_presences(
        self, presences: Sequence[Any], peer_id: PeerID
    ) -> None:
        """
        Process received block presences (v1.2.0).

        Tracks both Have and DontHave messages for optimization and logging.
        DontHave messages help us know which peers don't have blocks, but we
        don't fail the request - we continue waiting for other peers or timeout.
        This matches IPFS Bitswap behavior.
        """
        for presence in presences:
            cid = parse_cid(presence.cid)
            has_block = presence.type == Message.Have

            logger.debug(
                f"Received presence from {peer_id} for "
                f"{format_cid_for_display(cid, max_len=16)}: "
                f"{'Have' if has_block else 'DontHave'}"
            )

            if has_block:
                # Peer has the block - we can expect it to arrive soon
                # Track which peer has it
                if peer_id not in self._expected_blocks:
                    self._expected_blocks[peer_id] = set()
                self._expected_blocks[peer_id].add(cid)
            else:
                # DontHave - peer confirms they don't have this block
                # Track DontHave responses for metrics/optimization
                if cid not in self._dont_have_responses:
                    self._dont_have_responses[cid] = set()
                self._dont_have_responses[cid].add(peer_id)

                logger.info(
                    f"  ℹ️  Peer {peer_id} doesn't have block "
                    f"{format_cid_for_display(cid, max_len=16)} "
                    f"(DontHave response) - will try other peers or timeout"
                )

    async def _read_message(self, stream: INetStream) -> Message | None:
        """Read a length-prefixed message from the stream."""
        try:
            # Read length prefix byte-by-byte (varint encoding)
            length_bytes = b""
            while True:
                byte = await stream.read(1)
                if not byte:
                    return None  # Stream closed
                length_bytes += byte
                # Check if this is the last byte of the varint (high bit not set)
                if byte[0] & 0x80 == 0:
                    break
                # Limit to max varint length (10 bytes for 64-bit values)
                if len(length_bytes) >= 10:
                    logger.error("Varint length prefix too long")
                    return None

            # Decode length
            length = varint.decode_bytes(length_bytes)

            if length > MAX_MESSAGE_SIZE:
                raise MessageTooLargeError(
                    f"Message size {length} exceeds maximum {MAX_MESSAGE_SIZE}"
                )

            # Read message data
            msg_data = b""
            remaining = length

            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    break
                msg_data += chunk
                remaining -= len(chunk)

            # Verify we read all expected bytes
            if len(msg_data) != length:
                logger.error(f"Expected {length} bytes but got {len(msg_data)}")
                return None

            # Parse message
            msg = Message()
            msg.ParseFromString(msg_data)
            return msg

        except StreamEOF:
            # Stream closed by remote peer - this is normal when transfer completes
            logger.debug("Stream closed by remote peer")
            return None
        except Exception as e:
            logger.error(f"Error reading message: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def _write_message(self, stream: INetStream, msg: Message) -> None:
        """
        Write a length-prefixed message to the stream.

        Since blocks are already chunked at 63 KB (below the stream write limit
        of ~64 KB), we can write messages directly without additional chunking.
        """
        # Serialize message
        msg_bytes = msg.SerializeToString()

        if len(msg_bytes) > MAX_MESSAGE_SIZE:
            raise MessageTooLargeError(
                f"Message size {len(msg_bytes)} exceeds maximum {MAX_MESSAGE_SIZE}"
            )

        # Write length prefix and message
        length_prefix = varint.encode(len(msg_bytes))
        await stream.write(length_prefix + msg_bytes)

    async def _write_message_bytes(
        self, stream: INetStream, msg_bytes: bytes
    ) -> None:
        """
        Write pre-serialized message bytes (for 1.3.0 Message_1_3 objects).
        """
        if len(msg_bytes) > MAX_MESSAGE_SIZE:
            raise MessageTooLargeError(
                f"Message size {len(msg_bytes)} exceeds maximum {MAX_MESSAGE_SIZE}"
            )
        length_prefix = varint.encode(len(msg_bytes))
        await stream.write(length_prefix + msg_bytes)

    async def _process_block_presences_1_3(
        self, presences: Any, peer_id: PeerID
    ) -> None:
        """
        Process block presences from a 1.3.0 message.
        Handles PaymentRequired (type=2) in addition to Have/DontHave.
        """
        for presence in presences:
            cid_bytes = bytes(presence.cid)
            try:
                cid = parse_cid(cid_bytes)
            except Exception:
                continue

            presence_type = presence.type

            if presence_type == 0:  # Have
                if peer_id not in self._expected_blocks:
                    self._expected_blocks[peer_id] = set()
                self._expected_blocks[peer_id].add(cid)
                logger.debug(
                    f"[1.3.0] Peer {peer_id} has block "
                    f"{format_cid_for_display(cid, max_len=16)}"
                )
            elif presence_type == 1:  # DontHave
                if cid not in self._dont_have_responses:
                    self._dont_have_responses[cid] = set()
                self._dont_have_responses[cid].add(peer_id)
                logger.info(
                    f"[1.3.0] Peer {peer_id} doesn't have block "
                    f"{format_cid_for_display(cid, max_len=16)}"
                )
            elif presence_type == 2:  # PaymentRequired
                logger.info(
                    f"[1.3.0] Peer {peer_id} requires payment for block "
                    f"{format_cid_for_display(cid, max_len=16)} "
                    f"(PaymentTerms will follow in same message)"
                )
                # The payment_client will handle PaymentTerms
                # in process_incoming_message


