"""
Bitswap client implementation for block exchange.
Supports v1.0.0, v1.1.0, v1.2.0, and v1.3.0 protocols.
"""

from collections.abc import Sequence
import hashlib
import logging
from typing import TYPE_CHECKING, Any

import trio
import varint

from libp2p.abc import IHost, INetStream, INotifee
from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import StreamEOF, StreamError
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import PeerInfo  # noqa: F401

if TYPE_CHECKING:
    from .extension import IBitswapExtension
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
    BITSWAP_PROTOCOLS,
    DEFAULT_PRIORITY,
    MAX_BLOCK_SIZE,
    MAX_MESSAGE_SIZE,
)
from .decision_engine import BitswapDecisionEngine
from .errors import (
    BlockTooLargeError,
    MessageTooLargeError,
)
from .message_queue import BitswapMessageQueue
from .messages import create_message, create_wantlist_entry
from .pb.bitswap_pb2 import Message
from .peer_manager import BitswapPeerManager
from .presence import BlockPresenceManager
from .provider_query import ProviderQueryManager
from .session import BitswapSession
from .sim import SessionInterestManager

logger = logging.getLogger(__name__)


class BitswapClient(INotifee):
    """
    Bitswap client for exchanging blocks with other peers.

    Supports Bitswap protocol versions 1.0.0, 1.1.0, 1.2.0, and 1.3.0 for
    content discovery and file sharing in a peer-to-peer network.

    For 1.3.0 payment support, register a PaymentExtension.

    Implements :class:`~libp2p.abc.INotifee` so that per-peer state (wantlists,
    negotiated protocols, peer stats, presence) is reaped when a peer's
    connection closes — otherwise it would accumulate for every peer a
    long-running node ever talks to.
    """

    def __init__(
        self,
        host: IHost,
        block_store: BlockStore | None = None,
        protocol_version: str = BITSWAP_PROTOCOL_V120,
        provider_query_manager: ProviderQueryManager | None = None,
        presence_ttl: float = 60.0,
    ) -> None:
        """
        Initialize a Bitswap client.

        Args:
            host: The libp2p host
            block_store: The block store to use (defaults to MemoryBlockStore)
            protocol_version: The Bitswap protocol version string to prefer
            provider_query_manager: Optional manager to handle DHT provider queries
            presence_ttl: Time-to-live for block presence tracking (default 60s)

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
        self.sim = SessionInterestManager()
        self._peer_protocols: dict[PeerID, str] = {}  # peer -> negotiated protocol
        self._peer_pending_bytes: dict[PeerID, int] = {}
        # peer -> pending bytes (v1.2.0)

        self.presence_manager = BlockPresenceManager(ttl_seconds=presence_ttl)
        self.peer_manager = BitswapPeerManager()

        self._message_queues: dict[PeerID, BitswapMessageQueue] = {}
        self.decision_engine = BitswapDecisionEngine(
            block_store=self.block_store,
            get_message_queue_fn=self.get_or_create_message_queue,
            num_workers=8,
        )

        self._nursery: trio.Nursery | None = None
        self._started = False
        self._cancel_scope: trio.CancelScope | None = None
        self._presence_cleanup_started = False
        self._notifee_registered = False

    def get_or_create_message_queue(self, peer_id: PeerID) -> BitswapMessageQueue:
        """Get existing persistent MessageQueue for a peer or create a new one."""
        if peer_id not in self._message_queues:
            queue = BitswapMessageQueue(
                host=self.host,
                peer_id=peer_id,
                supported_protocols=self.supported_protocols,
                on_stream_opened=self._on_message_queue_stream_opened,
            )
            if self._nursery is not None:
                queue.start(self._nursery)
            self._message_queues[peer_id] = queue
        return self._message_queues[peer_id]

    def _on_message_queue_stream_opened(
        self, stream: INetStream, peer_id: PeerID
    ) -> None:
        """Attach response reader whenever a new persistent stream opens."""
        if self._nursery is not None:
            self._nursery.start_soon(
                self._read_responses_from_stream, stream, peer_id, None
            )

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
                self._handle_stream,
            )

        self._started = True
        self._cancel_scope = trio.CancelScope()
        if self._nursery is not None:
            self.decision_engine.start(self._nursery)
            for queue in self._message_queues.values():
                queue.start(self._nursery)
            if not self._presence_cleanup_started:
                self._presence_cleanup_started = True
                self._nursery.start_soon(self._presence_cleanup_loop)
        # Register as a network notifee so per-peer state is reaped when a
        # peer disconnects (prevents unbounded per-peer accumulation on
        # long-running nodes).
        try:
            self.host.get_network().register_notifee(self)
            self._notifee_registered = True
        except Exception as e:
            logger.debug(f"Failed to register bitswap notifee: {e}")
        logger.info(f"Bitswap client started (protocol: {self.protocol_version})")

    async def _presence_cleanup_loop(self) -> None:
        """Periodic background task to clean up expired presence state."""
        if self._cancel_scope is None:
            return
        with self._cancel_scope:
            while self._started:
                await trio.sleep(10)
                self.presence_manager.cleanup_expired()

    async def stop(self) -> None:
        """Stop the Bitswap client."""
        if not self._started:
            return

        self._started = False
        self._presence_cleanup_started = False
        if self._cancel_scope is not None:
            self._cancel_scope.cancel()
        await self.decision_engine.stop()
        for queue in list(self._message_queues.values()):
            await queue.stop()
        self._message_queues.clear()

        if self._notifee_registered:
            try:
                self.host.get_network().remove_notifee(self)
            except Exception as e:
                logger.debug(f"Failed to unregister bitswap notifee: {e}")
            self._notifee_registered = False
        # Unregister stream handlers for all supported Bitswap protocols
        for protocol in self.supported_protocols:
            self.host.remove_stream_handler(TProtocol(protocol))
        # Clear wantlists and pending requests
        self._wantlist.clear()
        self._peer_wantlists.clear()
        # _pending_requests removed (handled by sessions)
        self._peer_protocols.clear()
        self.presence_manager = BlockPresenceManager(
            ttl_seconds=self.presence_manager.ttl
        )
        logger.info("Bitswap client stopped")

    def set_nursery(self, nursery: trio.Nursery) -> None:
        """Set the nursery for background tasks."""
        self._nursery = nursery
        if self._started:
            self.decision_engine.start(nursery)
            for queue in self._message_queues.values():
                queue.start(nursery)
        # The presence-cleanup loop can only run once a nursery is available;
        # if start() ran first, start it now.
        if self._started and not self._presence_cleanup_started:
            self._presence_cleanup_started = True
            nursery.start_soon(self._presence_cleanup_loop)

    # ── INotifee (network lifecycle hooks) ───────────────────────────────

    async def opened_stream(self, network: Any, stream: INetStream) -> None:
        """No-op — Bitswap does not track stream open events."""

    async def closed_stream(self, network: Any, stream: INetStream) -> None:
        """No-op — Bitswap does not track stream close events."""

    async def connected(self, network: Any, conn: Any) -> None:
        """No-op — per-peer state is created lazily on demand."""

    async def disconnected(self, network: Any, conn: Any) -> None:
        """
        Reap all per-peer state when a peer's *last* connection closes.

        ``disconnected`` fires once per ``SwarmConn`` that closes; a peer may
        hold several connections, so the state is only dropped once no
        connection to the peer remains (mirrors TagStoreNotifee's
        last-connection semantics).
        """
        peer_id = None
        try:
            if hasattr(conn, "muxed_conn") and conn.muxed_conn is not None:
                peer_id = getattr(conn.muxed_conn, "peer_id", None)
            if peer_id is None and hasattr(conn, "peer_id"):
                peer_id = conn.peer_id
            if peer_id is None and hasattr(conn, "get_remote_peer"):
                peer_id = conn.get_remote_peer()
        except Exception:
            return

        if peer_id is None:
            return

        try:
            remaining = network.get_connections(peer_id)
        except Exception:
            remaining = None
        if not remaining:
            self.cleanup_peer(peer_id)

    async def listen(self, network: Any, multiaddr: Any) -> None:
        """No-op."""

    async def listen_close(self, network: Any, multiaddr: Any) -> None:
        """No-op."""

    def cleanup_peer(self, peer_id: PeerID) -> None:
        """
        Drop all per-peer state accumulated for ``peer_id``.

        Called on peer disconnect so long-running nodes don't accumulate
        wantlists, negotiated protocols, presence and peer stats for every
        peer they have ever talked to.
        """
        self._peer_wantlists.pop(peer_id, None)
        self._peer_protocols.pop(peer_id, None)
        self._peer_pending_bytes.pop(peer_id, None)
        self.peer_manager.remove_peer(peer_id)
        self.presence_manager.remove_peer(peer_id)
        queue = self._message_queues.pop(peer_id, None)
        if queue is not None and self._nursery is not None:
            self._nursery.start_soon(queue.stop)
        logger.debug(f"Cleaned up per-peer state for {peer_id}")
        logger.debug(f"Cleaned up per-peer state for {peer_id}")

    def new_session(self) -> BitswapSession:
        """Create a new Bitswap session for fetching blocks."""
        session_id = id(self) ^ id(trio.current_time())
        return BitswapSession(self, session_id)

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

        if not verify_cid(cid_obj, data):
            raise ValueError(
                f"Block data does not match CID hash: {format_cid_for_display(cid_obj)}"
            )

        await self.block_store.put_block(cid_obj, data)
        logger.debug(
            f"Added block {format_cid_for_display(cid_obj, max_len=16)} to store"
        )

        # Notify sessions
        for session in self.sim.split_wanted_blocks(cid_obj):
            await session.receive_block(cid_obj, data)

        # Notify peers who wanted this block
        await self._notify_peers_about_block(cid_obj, data)

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

        Sends a WANT_HAVE and waits for a Have/DontHave response.
        Also returns True if the block is already in the local store.

        Args:
            cid: The CID of the block to check
            peer_id: Optional specific peer to query

        Returns:
            True if peer has the block, False otherwise

        """
        cid_obj = parse_cid(cid)

        # Fast path: block is already local
        if await self.block_store.has_block(cid_obj):
            return True

        # Add to wantlist with Have type
        await self.want_block(cid_obj, want_type=1, send_dont_have=True)

        # Send wantlist to peer(s)
        if peer_id:
            await self._send_wantlist_to_peer(peer_id, [cid_obj])
        else:
            await self._broadcast_wantlist([cid_obj])

        # Wait for Have/DontHave response via presence manager
        result = False
        try:
            with trio.fail_after(5.0):
                while True:
                    # Check if presence manager recorded a Have from any peer
                    expected_peers = self.presence_manager.get_expected_peers(cid_obj)
                    if expected_peers:
                        result = True
                        break
                    # Check if we got DontHave from all queried peers
                    dont_have_peers = self.presence_manager.get_dont_have_peers(cid_obj)
                    if peer_id and peer_id in dont_have_peers:
                        result = False
                        break
                    # Also check local store in case block arrived meanwhile
                    if await self.block_store.has_block(cid_obj):
                        result = True
                        break
                    await trio.sleep(0.1)
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

    async def _send_wantlist_to_peer(
        self, peer_id: PeerID, cids: list[CIDObject]
    ) -> bool:
        """Send wantlist to a specific peer via its persistent MessageQueue."""
        # Track expected blocks for this peer
        peer_id_str = str(peer_id)
        logger.info(
            f"Adding {len(cids)} CIDs to expected_blocks for peer {peer_id_str}"
        )
        for cid in cids:
            logger.info(f"  + {format_cid_for_display(cid)}")
            self.presence_manager.add_have(peer_id, cid)

        logger.info(
            f"Total expected blocks from {peer_id_str}: "
            f"{len(self.presence_manager.get_expected_for_peer(peer_id))}"
        )

        try:
            msg_queue = self.get_or_create_message_queue(peer_id)
            if msg_queue.negotiated_protocol:
                supports_1_2_0 = msg_queue.negotiated_protocol in (
                    BITSWAP_PROTOCOL_V120,
                    "ipfs/bitswap/1.3.0",
                    "/ipfs/bitswap/1.3.0",
                )
            else:
                supports_1_2_0 = BITSWAP_PROTOCOL_V120 in msg_queue.supported_protocols
            want_infos = {}
            for cid in cids:
                want_info = self._wantlist.get(
                    cid,
                    {
                        "priority": DEFAULT_PRIORITY,
                        "want_type": 0,
                        "send_dont_have": False,
                    },
                )
                want_infos[cid] = {
                    "priority": want_info["priority"],
                    "want_type": want_info.get("want_type", 0) if supports_1_2_0 else 0,
                    "send_dont_have": (
                        want_info.get("send_dont_have", False) if supports_1_2_0 else False
                    ),
                }
            msg_queue.add_wants(cids, want_infos=want_infos, full_wantlist=False)
            if not msg_queue._started:
                await msg_queue.flush()
                if self._nursery is None and msg_queue._stream is not None:
                    await self._read_responses_from_stream(
                        msg_queue._stream, peer_id, list(cids)
                    )
            return True
        except Exception as e:
            logger.error(f"Failed to send wantlist to peer {peer_id}: {e}")
            return False

    async def _broadcast_wantlist(self, cids: list[CIDObject]) -> None:
        """Broadcast wantlist to all connected peers, with backpressure."""
        import random

        peers = list(self.host.get_network().connections.keys())

        # Limit broadcast to a maximum number of peers to provide backpressure
        # and prevent overwhelming the network or triggering GO_AWAY.
        MAX_BROADCAST_PEERS = 20
        if len(peers) > MAX_BROADCAST_PEERS:
            peers = random.sample(peers, MAX_BROADCAST_PEERS)

        for peer_id in peers:
            if self._nursery:
                self._nursery.start_soon(self._send_wantlist_to_peer, peer_id, cids)
            else:
                await self._send_wantlist_to_peer(peer_id, cids)

    async def _broadcast_cancel(self, cid: CIDObject) -> None:
        """Broadcast a cancel message to all connected peers via MessageQueue."""
        peers = list(self.host.get_network().connections.keys())
        for peer_id in peers:
            try:
                msg_queue = self.get_or_create_message_queue(peer_id)
                msg_queue.add_cancels([cid])
            except Exception as e:
                logger.debug(f"Failed to send cancel to peer {peer_id}: {e}")

    async def _notify_peers_about_block(self, cid: CIDObject, data: bytes) -> None:
        """Notify peers who wanted this block via MessageQueue."""
        peers_to_notify = []

        # Find peers who want this block
        for peer_id, wantlist in self._peer_wantlists.items():
            if cid in wantlist:
                want_info = wantlist[cid]
                peers_to_notify.append((peer_id, want_info))

        # Queue block or presence to interested peers
        for peer_id, want_info in peers_to_notify:
            try:
                msg_queue = self.get_or_create_message_queue(peer_id)
                want_type = want_info.get("want_type", 0)

                if want_type == 1:  # Have request (v1.2.0)
                    msg_queue.add_presences([(cid, True)])
                else:  # Block request
                    peer_protocol = (
                        msg_queue.negotiated_protocol
                        or self._peer_protocols.get(peer_id, BITSWAP_PROTOCOL_V100)
                    )
                    if peer_protocol == BITSWAP_PROTOCOL_V100:
                        msg_queue.add_blocks_v100([data])
                    else:
                        prefix = get_cid_prefix(cid)
                        msg_queue.add_blocks_v110([(prefix, data)])
            except Exception as e:
                logger.error(f"Failed to send block to peer {peer_id}: {e}")

    async def _read_responses_from_stream(
        self,
        stream: INetStream,
        peer_id: PeerID,
        wanted_cids: list[CIDObject] | None = None,
    ) -> None:
        """
        Read responses from a stream after sending a wantlist.

        This keeps the stream open so the provider can send blocks back.
        Stops reading once all expected blocks are received or after a timeout.

        ``wanted_cids`` optionally scopes this reader to the exact CIDs its
        wantlist covered. Without it, the reader falls back to the peer-global
        expected set (which also contains CIDs requested by other concurrent
        streams to the same peer).
        """
        try:
            peer_id_str = str(peer_id)
            logger.info(f"Reading responses from {peer_id_str} on stream")
            message_count = 0
            # If no activity for 30s, consider the stream dead
            STREAM_IDLE_TIMEOUT = 30.0

            while True:
                # Check if we've received all expected blocks. When this stream
                # was opened for a specific set of CIDs, only those matter —
                # otherwise the reader would linger for the whole transfer
                # because other batches keep the peer's expected set non-empty.
                expected_cids = self.presence_manager.get_expected_for_peer(peer_id)
                if wanted_cids is not None:
                    remaining = len(set(wanted_cids) & expected_cids)
                else:
                    remaining = len(expected_cids)
                if remaining == 0:
                    logger.info(
                        f"All expected blocks received from "
                        f"{peer_id_str}, closing stream"
                    )
                    break
                else:
                    logger.debug(
                        f"Still expecting {remaining} blocks from {peer_id_str}"
                    )

                # Read message from provider with idle timeout
                logger.debug(f"Waiting for message from {peer_id_str}...")
                try:
                    with trio.fail_after(STREAM_IDLE_TIMEOUT):
                        msg = await self._read_message(stream)
                except trio.TooSlowError:
                    logger.warning(
                        f"Stream from {peer_id_str} idle for "
                        f"{STREAM_IDLE_TIMEOUT}s, closing"
                    )
                    break

                if msg is None:
                    logger.warning(f"Stream from {peer_id_str} closed by remote")
                    break

                message_count += 1
                logger.info(f"Received message #{message_count} from {peer_id_str}")

                # Process the response (blocks, presences, etc.)
                await self._process_message(msg, peer_id, stream)

        except Exception as e:
            peer_id_str = str(peer_id)
            logger.error(f"Stream from {peer_id_str} ended with error: {e}")
            import traceback

            logger.error(traceback.format_exc())
        finally:
            # The session owns the peer's expected-block accounting (it removes
            # entries when a batch completes or times out, and the presence
            # manager TTL reaps stragglers). This reader only reports —
            # non-destructively — which of the CIDs it was opened for were
            # still pending when the stream closed, so slow-but-ongoing batches
            # are not falsely flagged as lost and concurrent readers' tracking
            # is never disturbed.
            expected_cids = self.presence_manager.get_expected_for_peer(peer_id)
            if wanted_cids is not None:
                pending = [c for c in wanted_cids if c in expected_cids]
            else:
                pending = list(expected_cids)
            pending_strs = sorted({format_cid_for_display(c) for c in pending})
            if pending_strs:
                peer_id_str = str(peer_id)
                logger.warning(
                    f"⚠️  Stream for {peer_id_str} finished with {len(pending_strs)} "
                    f"blocks still pending: {pending_strs}"
                )
            try:
                await stream.close()
            except Exception as e:
                logger.debug(f"Error closing stream: {e}")

    async def _handle_stream(self, stream: INetStream) -> None:
        """Handle incoming Bitswap stream."""
        peer_id = stream.muxed_conn.peer_id
        logger.debug(f"Handling Bitswap stream from peer {peer_id}")

        protocol = stream.get_protocol()
        if protocol:
            self._peer_protocols[peer_id] = str(protocol)

        STREAM_IDLE_TIMEOUT = 60.0

        try:
            try:
                with trio.fail_after(STREAM_IDLE_TIMEOUT):
                    msg = await self._read_message(stream)
            except trio.TooSlowError:
                logger.warning(
                    f"Stream from {peer_id} idle for {STREAM_IDLE_TIMEOUT}s, closing"
                )
                return
            if msg is None:
                return

            await self._process_message(msg, peer_id, stream)

            while True:
                try:
                    with trio.fail_after(STREAM_IDLE_TIMEOUT):
                        msg = await self._read_message(stream)
                except trio.TooSlowError:
                    break
                if msg is None:
                    break
                await self._process_message(msg, peer_id, stream)

        except Exception as e:
            logger.error(f"Error handling stream from {peer_id}: {e}")
        finally:
            try:
                await stream.close()
            except Exception as e:
                logger.debug(f"Error closing stream from {peer_id}: {e}")

    async def _process_message(
        self, msg: Message, peer_id: PeerID, stream: INetStream
    ) -> None:
        """Process a received Bitswap message."""
        peer_id_str = str(peer_id)[:16]
        if msg.HasField("wantlist"):
            logger.debug(
                f"\n📥 RECEIVED WANTLIST from peer {peer_id_str} with "
                f"{len(msg.wantlist.entries)} entries"
            )

        # Detect peer protocol version from stream
        protocol = stream.get_protocol()
        if protocol:
            self._peer_protocols[peer_id] = str(protocol)

        peer_protocol = str(protocol) if protocol else BITSWAP_PROTOCOL_V100
        logger.debug(
            f"[FLOW] Negotiated protocol for peer {str(peer_id)[:20]}...: "
            f"{peer_protocol}"
        )

        # ── Protocol Extension Handling ─────────────────────────────────────
        if peer_protocol in self.protocol_handlers:
            handled = await self.protocol_handlers[peer_protocol].process_message(
                peer_id, msg.SerializeToString(), stream
            )
            if handled:
                return

        # ── Standard 1.0.0–1.2.0 message handling (always runs) ─────────
        if msg.HasField("wantlist"):
            handled = False
            if peer_protocol in self.protocol_handlers:
                handled = await self.protocol_handlers[peer_protocol].process_wantlist(
                    msg.wantlist, peer_id, stream
                )
            if not handled:
                await self._process_wantlist(msg.wantlist, peer_id, stream)

        if msg.blocks:
            await self._process_blocks_v100(list(msg.blocks), peer_id)

        if msg.payload:
            await self._process_blocks_v110(msg.payload, peer_id)

        if msg.blockPresences:
            await self._process_block_presences(msg.blockPresences, peer_id)

        # Track pending bytes from peer (v1.2.0 flow control hint)
        if msg.pendingBytes > 0:
            self._peer_pending_bytes[peer_id] = msg.pendingBytes

    async def _process_wantlist(
        self, wantlist: Message.Wantlist, peer_id: PeerID, stream: INetStream
    ) -> None:
        """Process a wantlist from a peer via DecisionEngine."""
        # Initialize peer wantlist if needed
        if peer_id not in self._peer_wantlists:
            self._peer_wantlists[peer_id] = {}

        peer_wantlist = self._peer_wantlists[peer_id]
        # Update based on full or incremental wantlist
        if wantlist.full:
            peer_wantlist.clear()

        # Get peer protocol for response format
        peer_protocol = self._peer_protocols.get(peer_id, BITSWAP_PROTOCOL_V100)

        logger.debug(
            f"[SERVER PROCESSING WANTLIST] from {str(peer_id)[:20]}... "
            f"entries={len(wantlist.entries)}  protocol={peer_protocol}"
        )

        parsed_entries = []
        blocks_to_send_v100 = []
        blocks_to_send_v110 = []
        presences_to_send = []

        for entry in wantlist.entries:
            try:
                entry_cid = parse_cid(entry.block)
                parsed_entries.append(entry)
                if entry.cancel:
                    peer_wantlist.pop(entry_cid, None)
                else:
                    peer_wantlist[entry_cid] = {
                        "priority": entry.priority,
                        "want_type": entry.wantType,
                        "send_dont_have": entry.sendDontHave,
                    }

                    # Check if block is available locally
                    try:
                        has_block = await self.block_store.has_block(entry_cid)
                    except Exception:
                        has_block = False

                    if has_block:
                        data = await self.block_store.get_block(entry_cid)
                        if data:
                            if peer_protocol == BITSWAP_PROTOCOL_V100:
                                blocks_to_send_v100.append(data)
                            else:
                                prefix = get_cid_prefix(entry_cid)
                                blocks_to_send_v110.append((prefix, data))
                    else:
                        if entry.wantType == 1 or entry.sendDontHave:
                            presences_to_send.append((entry_cid, False))
            except Exception:
                continue

        # If stream is writable, write responses immediately on this existing stream (0 new streams!).
        if blocks_to_send_v100 or blocks_to_send_v110 or presences_to_send:
            try:
                await self._send_wantlist_responses_inline(
                    stream,
                    peer_id,
                    blocks_to_send_v100,
                    blocks_to_send_v110,
                    presences_to_send,
                )
            except Exception as e:
                logger.debug(f"Failed to respond inline on stream: {e}")

    async def _send_wantlist_responses_inline(
        self,
        stream: INetStream,
        peer_id: PeerID,
        blocks_to_send_v100: list[bytes],
        blocks_to_send_v110: list[tuple[bytes, bytes]],
        presences_to_send: list[tuple[CIDObject, bool]],
    ) -> None:
        """Helper to send blocks on a specific stream."""
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
        expected_cids = self.presence_manager.get_expected_for_peer(peer_id)
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

                # Record delivery for peer scoring
                self.peer_manager.record_delivery(peer_id, matched_cid, len(block_data))

                # Tag high-performing peers (Connection Manager Integration)
                stats = self.peer_manager._get_stats(peer_id)
                if stats.blocks_delivered >= 1 and stats.ema_latency < 1.0:
                    try:
                        self.host.get_network().tag_peer(peer_id, "bitswap", 5)
                    except AttributeError:
                        pass

                # Remove from expected blocks for all peers
                self.presence_manager.remove_have_from_all(matched_cid)
                pid_str = (
                    str(peer_id)[:16] if hasattr(peer_id, "__str__") else "unknown"
                )
                logger.info(f"  ✓ Removed from expected blocks for peer {pid_str}")

                # Notify sessions
                sessions = self.sim.split_wanted_blocks(matched_cid)
                if sessions:
                    logger.info(f"  ✓ Notifying {len(sessions)} sessions")
                    for session in sessions:
                        await session.receive_block(matched_cid, block_data, peer_id)

                    if self._started and hasattr(self, "_nursery") and self._nursery:
                        self._nursery.start_soon(self.cancel_want, matched_cid)
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
        remaining = self.presence_manager.get_expected_for_peer(peer_id)
        if remaining:
            logger.warning(f"  Still waiting for {len(remaining)} blocks:")
            for i, cid in enumerate(remaining):
                logger.warning(f"    {i + 1}. {format_cid_for_display(cid)}")
        else:
            logger.info("  ✓ All blocks received from this peer!")
        logger.info("=" * 70)

    async def _process_blocks_v110(
        self, blocks: Sequence[Any], peer_id: PeerID
    ) -> None:
        """Process received blocks (v1.1.0+ format with prefix)."""
        logger.debug(f"Processing {len(blocks)} blocks (v1.1.0+) from peer {peer_id}")
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

            # Record delivery for peer scoring
            self.peer_manager.record_delivery(peer_id, cid, len(data))

            # Tag high-performing peers (Connection Manager Integration)
            stats = self.peer_manager._get_stats(peer_id)
            if stats.blocks_delivered >= 1 and stats.ema_latency < 1.0:
                try:
                    self.host.get_network().tag_peer(peer_id, "bitswap", 5)
                except AttributeError:
                    pass

            # Remove from expected blocks for all peers
            self.presence_manager.remove_have_from_all(cid)

            # Notify sessions
            sessions = self.sim.split_wanted_blocks(cid)
            if sessions:
                logger.debug(
                    f"Notifying {len(sessions)} sessions for "
                    f"{format_cid_for_display(cid, max_len=16)}..."
                )
                for session in sessions:
                    await session.receive_block(cid, data, peer_id)

                if self._started and self._nursery:
                    self._nursery.start_soon(self.cancel_want, cid)
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

        Tracks Have, DontHave, and PaymentRequired messages.
        PaymentRequired (type=2) means the peer HAS the block but requires
        payment — do NOT mark as DontHave.
        """
        for presence in presences:
            cid = parse_cid(presence.cid)

            if presence.type == Message.Have:
                logger.debug(
                    f"Received Have from {peer_id} for "
                    f"{format_cid_for_display(cid, max_len=16)}"
                )
                self.presence_manager.add_have(peer_id, cid)
            elif presence.type == 2:  # PaymentRequired (v1.3.0)
                # Peer has the block but wants payment — treat as "has block"
                logger.debug(
                    f"Received PaymentRequired from {peer_id} for "
                    f"{format_cid_for_display(cid, max_len=16)}"
                )
                self.presence_manager.add_have(peer_id, cid)
            else:  # DontHave (type=1 or unknown)
                logger.debug(
                    f"Received DontHave from {peer_id} for "
                    f"{format_cid_for_display(cid, max_len=16)}"
                )
                self.presence_manager.add_dont_have(peer_id, cid)
                self.presence_manager.remove_have(peer_id, cid)

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

        except (StreamEOF, StreamError) as e:
            # Stream closed or reset by remote peer - normal when transfer
            # completes or connection drops
            logger.debug(f"Stream closed or error by remote peer: {e}")
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

    async def _write_message_bytes(self, stream: INetStream, msg_bytes: bytes) -> None:
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
                self.presence_manager.add_have(peer_id, cid)
                logger.debug(
                    f"[1.3.0] Peer {peer_id} has block "
                    f"{format_cid_for_display(cid, max_len=16)}"
                )
            elif presence_type == 1:  # DontHave
                self.presence_manager.add_dont_have(peer_id, cid)
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
