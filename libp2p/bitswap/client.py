"""
Bitswap client implementation for block exchange.
Supports v1.0.0, v1.1.0, v1.2.0, and v1.3.0 protocols.
"""

import logging
import traceback
from typing import TYPE_CHECKING, Any

import trio

from libp2p.abc import IHost, INetStream
from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.peer.id import ID as PeerID

if TYPE_CHECKING:
    from .extension import IBitswapExtension
from .block_store import BlockStore, MemoryBlockStore
from .cid import (
    CIDInput,
    CIDObject,
    format_cid_for_display,
    get_cid_prefix,
    parse_cid,
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
    BitswapTimeoutError,
    BlockNotFoundError,
    BlockTooLargeError,
    MessageTooLargeError,
)
from .message_handler import BitswapMessageHandler
from .messages import create_message, create_wantlist_entry
from .pb.bitswap_pb2 import Message
from .provider_query import ProviderQueryManager
from .response_sender import BitswapResponseSender

logger = logging.getLogger(__name__)


class BitswapClient:
    """
    Bitswap client for exchanging blocks with other peers.

    Supports Bitswap protocol versions 1.0.0, 1.1.0, 1.2.0, and 1.3.0 for
    content discovery and file sharing in a peer-to-peer network.

    For 1.3.0 payment support, register a PaymentExtension.
    """

    def __init__(
        self,
        host: IHost,
        block_store: BlockStore | None = None,
        protocol_version: str = BITSWAP_PROTOCOL_V120,
        provider_query_manager: ProviderQueryManager | None = None,
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

        """
        self.host = host
        self.block_store = block_store or MemoryBlockStore()
        self.protocol_version = protocol_version
        self.provider_query_manager: ProviderQueryManager | None = (
            provider_query_manager
        )

        self.protocol_handlers: dict[str, "IBitswapExtension"] = {}
        self.supported_protocols: list[str] = list(BITSWAP_PROTOCOLS)

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
        self._have_confirmed: dict[
            CIDObject, set[PeerID]
        ] = {}  # cid -> peers who sent Have
        self._delivery_peers: dict[
            CIDObject, PeerID
        ] = {}  # cid -> peer_id that delivered it
        self._nursery: trio.Nursery | None = None
        self._started = False
        self._stream_limiter = trio.CapacityLimiter(50)
        self.response_sender = BitswapResponseSender(self)
        self.message_handler = BitswapMessageHandler(self, self.response_sender)

    def register_extension(self, protocol: str, extension: "IBitswapExtension") -> None:
        """Register an extension for a specific protocol."""
        extension.set_client(self)
        self.protocol_handlers[protocol] = extension
        if protocol not in self.supported_protocols:
            self.supported_protocols.insert(0, protocol)

    async def start(self) -> None:
        """Start the Bitswap client."""
        if self._started:
            return

        # Set stream handler for all supported Bitswap protocols
        for protocol in self.supported_protocols:
            self.host.set_stream_handler(
                TProtocol(protocol),
                self.message_handler.handle_stream,
            )

        self._started = True
        logger.info(f"Bitswap client started (protocol: {self.protocol_version})")

    async def stop(self) -> None:
        """Stop the Bitswap client."""
        if not self._started:
            return

        self._started = False
        # Unregister stream handlers for all supported Bitswap protocols
        for protocol in self.supported_protocols:
            self.host.remove_stream_handler(TProtocol(protocol))
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
                success = await self._send_wantlist_to_peer(peer_id, batch)
                if not success:
                    for cid_obj in batch:
                        if cid_obj in self._pending_requests:
                            del self._pending_requests[cid_obj]
                    raise Exception(f"Failed to send wantlist to peer {peer_id}")
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

    async def get_block_with_peer(
        self,
        cid: CIDInput,
        peer_id: PeerID | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> tuple[bytes, PeerID | None]:
        """
        Get a block and return the peer that delivered it.
        """
        cid_obj = parse_cid(cid)

        # 1. Check local store first
        data = await self.block_store.get_block(cid_obj)
        if data is not None:
            return data, None

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

    async def get_block(
        self,
        cid: CIDInput,
        peer_id: PeerID | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes:
        """
        Get a block, fetching from peers if not available locally.
        """
        data, _ = await self.get_block_with_peer(cid, peer_id, timeout)
        return data

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
        Check if a peer has a block (v1.2.0 feature), without fetching it.
        """
        cid_obj = parse_cid(cid)
        await self.want_block(cid_obj, want_type=1, send_dont_have=True)

        if peer_id:
            await self._send_wantlist_to_peer(peer_id, [cid_obj])
        else:
            await self._broadcast_wantlist([cid_obj])

        result = False
        try:
            with trio.fail_after(5.0):
                while True:
                    # Block already local (e.g. someone else fetched it meanwhile)
                    if await self.block_store.has_block(cid_obj):
                        result = True
                        break
                    # A HAVE presence was recorded for the peer(s) we asked
                    if peer_id is not None:
                        if peer_id in self._have_confirmed.get(cid_obj, set()):
                            result = True
                            break
                    elif len(self._have_confirmed.get(cid_obj, set())) > 0:
                        result = True
                        break
                    # An explicit DontHave from the peer we asked
                    # short-circuits the wait
                    if peer_id is not None and peer_id in self._dont_have_responses.get(
                        cid_obj, set()
                    ):
                        break
                    await trio.sleep(0.1)
        except trio.TooSlowError:
            result = False
        finally:
            # Don't clear entries other pending get_block() calls may still need
            self._expected_blocks.get(peer_id or PeerID(b""), set()).discard(cid_obj)
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
    ) -> tuple[bytes, PeerID | None]:
        """Request a block from the network."""
        logger.info(f"📤 Requesting block: {format_cid_for_display(cid)}")

        # Add to wantlist with sendDontHave=True for v1.2.0
        await self.want_block(cid, send_dont_have=True)

        # Create pending request event
        if cid not in self._pending_requests:
            self._pending_requests[cid] = trio.Event()

        # Send wantlist to peers
        if peer_id:
            success = await self._send_wantlist_to_peer(peer_id, [cid])
            if not success:
                if cid in self._pending_requests:
                    del self._pending_requests[cid]
                raise Exception(f"Failed to send wantlist to peer {peer_id}")
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
                raise BlockNotFoundError(
                    f"Block {format_cid_for_display(cid)} delivered but not in store"
                )
            result = data
            logger.info(f"  ✓ Block received! Size: {len(data)} bytes")
        except trio.TooSlowError as e:
            logger.error(f"  ✗ TIMEOUT waiting for block {format_cid_for_display(cid)}")
            error = BitswapTimeoutError(
                f"Timeout waiting for block {format_cid_for_display(cid, max_len=16)} "
                f"after {timeout}s"
            )
            error.__cause__ = e
            raise error
        finally:
            # Cleanup
            await self.cancel_want(cid)
            if cid in self._pending_requests:
                del self._pending_requests[cid]
            if cid in self._dont_have_responses:
                del self._dont_have_responses[cid]

        delivering_peer = self._delivery_peers.pop(cid, None)
        assert result is not None
        return result, delivering_peer

    async def _send_wantlist_to_peer(
        self, peer_id: PeerID, cids: list[CIDObject]
    ) -> bool:
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
                protocols = [TProtocol(p) for p in self.supported_protocols]  # Try all

            # Open stream and send message
            async with self._stream_limiter:
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
                    self.message_handler.read_responses_from_stream, stream, peer_id
                )
            else:
                await self.message_handler.read_responses_from_stream(stream, peer_id)
            return True

        except Exception as e:
            logger.error(f"Failed to send wantlist to peer {peer_id}: {e}")
            return False

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
        for peer_id, wantlist in list(self._peer_wantlists.items()):
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

    async def _read_message(self, stream: INetStream) -> Message | None:
        """Read a length-prefixed message from the stream."""
        from libp2p.io.exceptions import IncompleteReadError
        from libp2p.io.utils import read_exactly
        from libp2p.utils.varint import decode_uvarint_from_stream

        try:
            # Read length
            try:
                length = await decode_uvarint_from_stream(stream)
            except (IncompleteReadError, EOFError):
                return None

            if length > MAX_MESSAGE_SIZE:
                raise MessageTooLargeError(
                    f"Message size {length} exceeds maximum {MAX_MESSAGE_SIZE}"
                )

            # Read message data
            msg_data = await read_exactly(stream, length)

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
            logger.error(traceback.format_exc())
            return None

    async def _write_message(self, stream: INetStream, msg: Message) -> None:
        """
        Write a length-prefixed message to the stream.
        """
        await self._write_message_bytes(stream, msg.SerializeToString())

    async def _write_message_bytes(self, stream: INetStream, msg_bytes: bytes) -> None:
        """
        Write pre-serialized message bytes (for 1.3.0 Message_1_3 objects).
        """
        if len(msg_bytes) > MAX_MESSAGE_SIZE:
            raise MessageTooLargeError(
                f"Message size {len(msg_bytes)} exceeds maximum {MAX_MESSAGE_SIZE}"
            )
        from libp2p.utils.varint import encode_uvarint

        length_prefix = encode_uvarint(len(msg_bytes))
        await stream.write(length_prefix + msg_bytes)
