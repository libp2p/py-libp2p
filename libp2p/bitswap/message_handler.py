"""
Bitswap message handler for reading streams and processing messages.
"""

from collections.abc import Sequence
import logging
import traceback
from typing import TYPE_CHECKING, Any

from libp2p.abc import INetStream
from libp2p.peer.id import ID as PeerID

from .cid import (
    CIDObject,
    format_cid_for_display,
    get_cid_prefix,
    parse_cid,
    reconstruct_cid_from_prefix_and_data,
    verify_cid,
)
from .config import BITSWAP_PROTOCOL_V100, MAX_BLOCK_SIZE
from .pb.bitswap_pb2 import Message

if TYPE_CHECKING:
    from .client import BitswapClient
    from .response_sender import BitswapResponseSender

logger = logging.getLogger(__name__)


class BitswapMessageHandler:
    """Handles incoming Bitswap streams and messages."""

    def __init__(
        self, client: "BitswapClient", response_sender: "BitswapResponseSender"
    ):
        self.client = client
        self.response_sender = response_sender

    async def handle_stream(self, stream: INetStream) -> None:
        """Handle incoming Bitswap stream."""
        peer_id = stream.muxed_conn.peer_id
        logger.debug(f"Handling Bitswap stream from peer {peer_id}")

        protocol = stream.get_protocol()
        if protocol:
            self.client._peer_protocols[peer_id] = str(protocol)

        try:
            msg = await self.client._read_message(stream)
            if msg is None:
                return

            await self.process_message(msg, peer_id, stream)

            while True:
                msg = await self.client._read_message(stream)
                if msg is None:
                    break
                await self.process_message(msg, peer_id, stream)

        except Exception as e:
            logger.error(f"Error handling stream from {peer_id}: {e}")
        finally:
            await stream.close()

    async def read_responses_from_stream(
        self, stream: INetStream, peer_id: PeerID
    ) -> None:
        """
        Read responses from a stream after sending a wantlist.
        """
        try:
            peer_id_str = str(peer_id)
            logger.info(f"📡 Reading responses from {peer_id_str} on stream")
            message_count = 0

            while True:
                if peer_id in self.client._expected_blocks:
                    remaining = len(self.client._expected_blocks[peer_id])
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

                logger.debug(f"Waiting for message from {peer_id_str}...")
                msg = await self.client._read_message(stream)
                if msg is None:
                    logger.warning(f"Stream from {peer_id_str} closed by remote")
                    break

                message_count += 1
                logger.info(f"📨 Received message #{message_count} from {peer_id_str}")

                await self.process_message(msg, peer_id, stream)

        except Exception as e:
            peer_id_str = str(peer_id)
            logger.error(f"Stream from {peer_id_str} ended with error: {e}")
            logger.error(traceback.format_exc())
        finally:
            if peer_id in self.client._expected_blocks:
                peer_id_str = str(peer_id)
                remaining = len(self.client._expected_blocks[peer_id])
                if remaining > 0:
                    logger.error("")
                    logger.error("=" * 70)
                    logger.error("⚠️  STREAM CLOSED WITH MISSING BLOCKS")
                    logger.error("=" * 70)
                    logger.error(f"Peer: {peer_id_str}")
                    logger.error(f"Missing {remaining} blocks:")
                    for i, cid in enumerate(self.client._expected_blocks[peer_id]):
                        logger.error(f"  {i + 1}. {format_cid_for_display(cid)}")
                    logger.error("=" * 70)
                    logger.error("")
                del self.client._expected_blocks[peer_id]
            try:
                await stream.close()
            except Exception as e:
                logger.debug(f"Error closing stream: {e}")

    async def process_message(
        self, msg: Message, peer_id: PeerID, stream: INetStream
    ) -> None:
        """Process a received Bitswap message."""
        peer_id_str = str(peer_id)[:16]
        if msg.HasField("wantlist"):
            logger.debug(
                f"\n📥 RECEIVED WANTLIST from peer {peer_id_str} with "
                f"{len(msg.wantlist.entries)} entries"
            )

        protocol = stream.get_protocol()
        if protocol:
            self.client._peer_protocols[peer_id] = str(protocol)

        peer_protocol = str(protocol) if protocol else BITSWAP_PROTOCOL_V100
        logger.info(
            f"[FLOW] Negotiated protocol for peer {str(peer_id)[:20]}...: "
            f"{peer_protocol}"
        )

        if peer_protocol in self.client.protocol_handlers:
            handler = self.client.protocol_handlers[peer_protocol]
            handled = await handler.process_message(
                peer_id, msg.SerializeToString(), stream
            )
            if handled:
                return

        if msg.HasField("wantlist"):
            handled = False
            if peer_protocol in self.client.protocol_handlers:
                handler = self.client.protocol_handlers[peer_protocol]
                handled = await handler.process_wantlist(msg.wantlist, peer_id, stream)
            if not handled:
                await self.process_wantlist(msg.wantlist, peer_id, stream)

        if msg.blocks:
            await self.process_blocks_v100(list(msg.blocks), peer_id)

        if msg.payload:
            await self.process_blocks_v110(msg.payload, peer_id)

        if msg.blockPresences:
            await self.process_block_presences(msg.blockPresences, peer_id)

    async def process_wantlist(
        self, wantlist: Message.Wantlist, peer_id: PeerID, stream: INetStream
    ) -> None:
        """Process a wantlist from a peer."""
        if peer_id not in self.client._peer_wantlists:
            self.client._peer_wantlists[peer_id] = {}

        peer_wantlist = self.client._peer_wantlists[peer_id]
        if wantlist.full:
            peer_wantlist.clear()

        peer_protocol = self.client._peer_protocols.get(peer_id, BITSWAP_PROTOCOL_V100)

        logger.debug(
            f"[STEP 1] SERVER PROCESSING WANTLIST from {str(peer_id)[:20]}...\n"
            f"   entries={len(wantlist.entries)}  protocol={peer_protocol}"
        )

        blocks_to_send_v100 = []
        blocks_to_send_v110 = []
        presences_to_send = []

        for entry in wantlist.entries:
            try:
                logger.debug(f"  -> Processing entry: {bytes(entry.block).hex()}")
                entry_cid = parse_cid(entry.block)
                logger.debug(f"  -> Parsed CID: {entry_cid}")
            except Exception as e:
                logger.debug(f"  -> EXCEPTION in parse_cid: {e}")
                continue

            if entry.cancel:
                if entry_cid in peer_wantlist:
                    del peer_wantlist[entry_cid]
            else:
                peer_wantlist[entry_cid] = {
                    "priority": entry.priority,
                    "want_type": entry.wantType,
                    "send_dont_have": entry.sendDontHave,
                }

                logger.debug(f"  -> Checking if we have block {entry_cid}")
                try:
                    has_block = await self.client.block_store.has_block(entry_cid)
                    logger.debug(f"  -> has_block result: {has_block}")
                except Exception as e:
                    logger.debug(f"  -> EXCEPTION in has_block: {e}")
                    has_block = False

                logger.debug(
                    f"[WANTLIST ENTRY] "
                    f"cid={format_cid_for_display(entry_cid, max_len=16)} "
                    f"wantType={entry.wantType} cancel={entry.cancel} "
                    f"has_block={has_block}"
                )

                if entry.wantType == 1:
                    if has_block:
                        data = await self.client.block_store.get_block(entry_cid)
                        if data:
                            logger.debug(
                                f"\n[WANT_HAVE] Sending block directly "
                                f"({len(data)} bytes) for "
                                f"{format_cid_for_display(entry_cid, max_len=16)} "
                                f"(skipping HAVE presence to avoid Go re-request)"
                            )
                            if peer_protocol == BITSWAP_PROTOCOL_V100:
                                blocks_to_send_v100.append(data)
                            else:
                                prefix = get_cid_prefix(entry_cid)
                                blocks_to_send_v110.append((prefix, data))
                    else:
                        logger.debug(
                            f"\n[WANT_HAVE] DontHave for "
                            f"{format_cid_for_display(entry_cid, max_len=16)}"
                        )
                        presences_to_send.append((entry_cid, False))
                else:
                    if has_block:
                        data = await self.client.block_store.get_block(entry_cid)
                        if data:
                            logger.debug(
                                f"\n[WANT_BLOCK] Sending block directly "
                                f"({len(data)} bytes) for "
                                f"{format_cid_for_display(entry_cid, max_len=16)}"
                            )
                            if peer_protocol == BITSWAP_PROTOCOL_V100:
                                blocks_to_send_v100.append(data)
                            else:
                                prefix = get_cid_prefix(entry_cid)
                                blocks_to_send_v110.append((prefix, data))
                    else:
                        presences_to_send.append((entry_cid, False))

        if blocks_to_send_v100 or blocks_to_send_v110 or presences_to_send:
            if self.client._nursery is not None:
                self.client._nursery.start_soon(
                    self.response_sender.send_wantlist_responses_bg,  # type: ignore
                    peer_id,
                    str(peer_protocol),
                    blocks_to_send_v100,
                    blocks_to_send_v110,
                    presences_to_send,
                )
            else:
                await self.response_sender.send_wantlist_responses_inline(
                    stream,
                    peer_id,
                    blocks_to_send_v100,
                    blocks_to_send_v110,
                    presences_to_send,
                )

    async def store_and_notify(
        self, cid: CIDObject, data: bytes, peer_id: PeerID
    ) -> None:
        """Store a received block, remove it from expected lists, and notify waiters."""
        await self.client.block_store.put_block(cid, data)
        logger.debug(f"Stored block {format_cid_for_display(cid, max_len=16)}")

        for pid in list(self.client._expected_blocks.keys()):
            if cid in self.client._expected_blocks[pid]:
                self.client._expected_blocks[pid].discard(cid)

        if cid in self.client._pending_requests:
            cid_str = format_cid_for_display(cid, max_len=16)
            logger.debug(f"Notifying pending request for {cid_str}")
            self.client._delivery_peers[cid] = peer_id
            self.client._pending_requests[cid].set()

    async def process_blocks_v100(self, blocks: list[bytes], peer_id: PeerID) -> None:
        """Process received blocks (v1.0.0 format)."""
        peer_id_str = str(peer_id)[:16] if hasattr(peer_id, "__str__") else "unknown"
        logger.debug(
            f"Processing {len(blocks)} blocks (v1.0.0) from peer {peer_id_str}"
        )

        expected_cids = self.client._expected_blocks.get(peer_id, set()).copy()

        # Group by unique CID prefixes (version, codec, hash alg) to avoid
        # hashing block_data O(N) times. Usually there's only 1-2 unique prefixes.
        unique_prefixes = {}
        for cid in expected_cids:
            try:
                prefix = cid.prefix()
                unique_prefixes[prefix.to_bytes()] = prefix
            except ValueError:
                pass

        for idx, block_data in enumerate(blocks):
            if len(block_data) > MAX_BLOCK_SIZE:
                logger.warning(
                    f"Rejecting block from {peer_id_str}: "
                    f"size {len(block_data)} exceeds limit {MAX_BLOCK_SIZE}"
                )
                continue
            matched_cid = None
            for prefix in unique_prefixes.values():
                try:
                    recomputed_cid = prefix.sum(block_data)
                    if recomputed_cid in expected_cids:
                        matched_cid = recomputed_cid
                        break
                except ValueError:
                    pass

            if not matched_cid:
                # Fallback to linear scan for any edge cases where prefix() failed
                for cid in expected_cids:
                    if verify_cid(cid, block_data):
                        matched_cid = cid
                        break

            if matched_cid:
                await self.store_and_notify(matched_cid, block_data, peer_id)
            else:
                logger.error(f"Block doesn't match any expected CID from {peer_id_str}")

        remaining = self.client._expected_blocks.get(peer_id, set())
        if remaining:
            logger.debug(
                f"Still waiting for {len(remaining)} blocks from {peer_id_str}"
            )

    async def process_blocks_v110(self, blocks: Sequence[Any], peer_id: PeerID) -> None:
        """Process received blocks (v1.1.0+ format with prefix)."""
        logger.debug(f"Processing {len(blocks)} blocks (v1.1.0+)")
        for block in blocks:
            prefix = block.prefix
            data = block.data

            if len(data) > MAX_BLOCK_SIZE:
                logger.warning(
                    f"Rejecting block from {peer_id}: "
                    f"size {len(data)} exceeds limit {MAX_BLOCK_SIZE}"
                )
                continue

            cid_bytes = reconstruct_cid_from_prefix_and_data(prefix, data)
            cid = parse_cid(cid_bytes)

            await self.store_and_notify(cid, data, peer_id)

    async def process_block_presences(
        self, presences: Sequence[Any], peer_id: PeerID
    ) -> None:
        """Process received block presences (v1.2.0)."""
        for presence in presences:
            cid = parse_cid(presence.cid)
            has_block = presence.type == Message.Have

            logger.debug(
                f"Received presence from {peer_id} for "
                f"{format_cid_for_display(cid, max_len=16)}: "
                f"{'Have' if has_block else 'DontHave'}"
            )

            if has_block:
                if peer_id not in self.client._expected_blocks:
                    self.client._expected_blocks[peer_id] = set()
                self.client._expected_blocks[peer_id].add(cid)
                if cid not in self.client._have_confirmed:
                    self.client._have_confirmed[cid] = set()
                self.client._have_confirmed[cid].add(peer_id)
            else:
                if cid not in self.client._dont_have_responses:
                    self.client._dont_have_responses[cid] = set()
                self.client._dont_have_responses[cid].add(peer_id)

                logger.info(
                    f"  ℹ️  Peer {peer_id} doesn't have block "
                    f"{format_cid_for_display(cid, max_len=16)} "
                    f"(DontHave response) - will try other peers or timeout"
                )

    async def process_block_presences_1_3(
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
                if peer_id not in self.client._expected_blocks:
                    self.client._expected_blocks[peer_id] = set()
                self.client._expected_blocks[peer_id].add(cid)
                if cid not in self.client._have_confirmed:
                    self.client._have_confirmed[cid] = set()
                self.client._have_confirmed[cid].add(peer_id)
                logger.debug(
                    f"[1.3.0] Peer {peer_id} has block "
                    f"{format_cid_for_display(cid, max_len=16)}"
                )
            elif presence_type == 1:  # DontHave
                if cid not in self.client._dont_have_responses:
                    self.client._dont_have_responses[cid] = set()
                self.client._dont_have_responses[cid].add(peer_id)
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
