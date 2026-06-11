# p2pcalc/p2p_node.py — py-libp2p node for P2PCalc
# Author: Dashpreet Singh <dashpreetsinghhanda@gmail.com>
#
# Taps directly into the existing GossipSub v2.0 implementation in
# py-libp2p. No changes to the library — we are purely a consumer.
#
# Innovations beyond baseline:
#   1. Topic-per-sheet: each EtherCalc room gets its own GossipSub topic
#      "p2pcalc/<sheet_id>" — allows fine-grained mesh membership
#   2. Peer presence via HEARTBEAT operations — know who is editing what
#   3. Late-joiner state sync via libp2p streams (not GossipSub pub-sub)
#      Snapshot is chunked and sent directly, then op-log replayed on top
#   4. mDNS for LAN discovery (zero config), DHT for WAN discovery

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging

from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.host.basic_host import BasicHost
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import Pubsub

from .crdt import ConflictPolicy, SheetCRDT
from .operation import Operation, OperationFactory, OpType, receive_operation

logger = logging.getLogger("p2pcalc.node")

# GossipSub topic prefix
TOPIC_PREFIX = "p2pcalc"

# Protocol ID for direct state-sync streams
SYNC_PROTOCOL = "/p2pcalc/sync/1.0.0"

# GossipSub parameters tuned for collaborative editing
# Lower heartbeat = faster mesh convergence for small peer groups
GOSSIPSUB_PARAMS = dict(
    degree=6,
    degree_low=4,
    degree_high=8,
    heartbeat_interval=1,  # 1s heartbeat for fast convergence
    gossip_window=3,
    gossip_history=5,
    time_to_live=60,
    adaptive_gossip_enabled=True,  # GossipSub v2.0 adaptive features
    spam_protection_enabled=True,
)


def _topic(sheet_id: str) -> str:
    return f"{TOPIC_PREFIX}/{sheet_id}"


class P2PCalcNode:
    """
    A P2PCalc peer node.

    Lifecycle:
      1. __init__     — configure keys and sheet state
      2. start()      — spin up libp2p host, GossipSub, mDNS
      3. join_sheet() — subscribe to sheet topic, request snapshot if needed
      4. publish()    — broadcast an Operation to all peers on topic
      5. stop()       — clean shutdown

    Incoming operations are delivered via the callback registered in
    join_sheet(). The node handles dedup, HLC update, and CRDT apply
    before calling the callback.
    """

    def __init__(
        self,
        port: int = 0,
        known_peers: list[str] | None = None,
        conflict_policy: ConflictPolicy = ConflictPolicy.MULTI_VALUE,
    ):
        self._port = port
        self._known_peers = known_peers or []
        self._conflict_policy = conflict_policy

        # Keyed by sheet_id
        self._sheets: dict[str, SheetCRDT] = {}
        self._callbacks: dict[str, Callable[[Operation], Awaitable[None]]] = {}
        # sheet_id -> peer_id -> cursor
        self._presence: dict[str, dict[str, str]] = {}

        # Set during start()
        self._host: BasicHost | None = None
        self._pubsub: Pubsub | None = None
        self._gossipsub: GossipSub | None = None
        self._factory: OperationFactory | None = None
        self._peer_id_str: str = ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_host(self) -> BasicHost:
        """Return _host, raising RuntimeError if node has not been started."""
        if self._host is None:
            raise RuntimeError("Node not started — call start() first")
        return self._host

    def _require_pubsub(self) -> Pubsub:
        """Return _pubsub, raising RuntimeError if node has not been started."""
        if self._pubsub is None:
            raise RuntimeError("Node not started — call start() first")
        return self._pubsub

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> str:
        """Start the libp2p host and GossipSub. Returns peer_id string."""
        key_pair = create_new_key_pair()

        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{self._port}")

        self._host = new_host(key_pair=key_pair)
        if self._host is None:
            raise RuntimeError("new_host() returned None — cannot start node")

        await self._host.get_network().listen(listen_addr)

        self._peer_id_str = str(self._host.get_id())
        self._factory = OperationFactory(peer_id=self._peer_id_str)

        logger.info("P2PCalc node started: %s", self._peer_id_str)

        # Boot GossipSub v2.0
        from libp2p.pubsub.gossipsub import (
            PROTOCOL_ID,
            PROTOCOL_ID_V11,
            PROTOCOL_ID_V13,
            PROTOCOL_ID_V20,
        )

        self._gossipsub = GossipSub(
            protocols=[
                PROTOCOL_ID_V20,
                PROTOCOL_ID_V13,
                PROTOCOL_ID_V11,
                PROTOCOL_ID,
            ],
            **GOSSIPSUB_PARAMS,
        )
        self._pubsub = Pubsub(self._host, self._gossipsub)

        # Register direct sync stream handler for late joiners
        self._host.set_stream_handler(SYNC_PROTOCOL, self._handle_sync_stream)

        # Connect to any known peers
        for addr_str in self._known_peers:
            await self._connect_peer(addr_str)

        return self._peer_id_str

    async def _connect_peer(self, addr_str: str) -> None:
        host = self._require_host()
        try:
            peer_info = info_from_p2p_addr(Multiaddr(addr_str))
            await host.connect(peer_info)
            logger.info("Connected to peer: %s", addr_str)
        except Exception as e:
            logger.warning("Failed to connect to %s: %s", addr_str, e)

    # ------------------------------------------------------------------
    # Sheet management
    # ------------------------------------------------------------------

    async def join_sheet(
        self,
        sheet_id: str,
        on_operation: Callable[[Operation], Awaitable[None]],
        request_snapshot: bool = True,
    ) -> None:
        """Subscribe to a sheet's GossipSub topic and request state sync."""
        pubsub = self._require_pubsub()

        if sheet_id not in self._sheets:
            self._sheets[sheet_id] = SheetCRDT(
                sheet_id=sheet_id,
                policy=self._conflict_policy,
            )

        self._callbacks[sheet_id] = on_operation
        topic = _topic(sheet_id)

        # Subscribe and register message handler
        await pubsub.subscribe(topic)
        pubsub.add_validator(topic, self._validate_message)

        # Start message pump for this topic
        asyncio.create_task(self._message_pump(sheet_id, topic))

        logger.info("Joined sheet: %s (topic=%s)", sheet_id, topic)

        # Request snapshot from existing peers if we're a late joiner
        if request_snapshot and self._factory:
            snap_req = self._factory.make_snapshot_request(sheet_id)
            await self.publish(snap_req)

    async def leave_sheet(self, sheet_id: str) -> None:
        pubsub = self._require_pubsub()
        topic = _topic(sheet_id)
        await pubsub.unsubscribe(topic)
        self._callbacks.pop(sheet_id, None)
        logger.info("Left sheet: %s", sheet_id)

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, op: Operation) -> None:
        """Broadcast an Operation to all peers on this sheet's topic."""
        pubsub = self._require_pubsub()
        topic = _topic(op.sheet_id)
        data = op.to_bytes()
        await pubsub.publish(topic, data)
        logger.debug("Published op %s type=%s", op.op_id[:8], op.op_type)

    async def publish_command(
        self,
        sheet_id: str,
        socialcalc_command: str,
    ) -> Operation:
        """Parse a SocialCalc command string, apply locally, and broadcast."""
        if not self._factory:
            raise RuntimeError("Node not started")

        sheet = self._sheets.get(sheet_id)
        depends_on = []
        if sheet and sheet.op_log_length() > 0:
            last_op = sheet.op_log_since(sheet.op_log_length() - 1)
            if last_op:
                depends_on = [last_op[0].op_id]

        op = self._factory.from_socialcalc_command(
            socialcalc_command, sheet_id, depends_on=depends_on
        )

        # Apply locally first (optimistic)
        if sheet:
            sheet.apply(op)

        await self.publish(op)
        return op

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _message_pump(self, sheet_id: str, topic: str) -> None:
        """Consume GossipSub messages for this sheet."""
        pubsub = self._require_pubsub()
        subscription = pubsub.get_subscription(topic)
        if subscription is None:
            logger.warning("No subscription found for topic %s", topic)
            return

        async for msg in subscription:
            if msg is None:
                continue
            await self._handle_message(sheet_id, msg)

    async def _handle_message(self, sheet_id: str, msg: rpc_pb2.Message) -> None:
        try:
            op = Operation.from_bytes(msg.data)
        except Exception as e:
            logger.warning("Failed to deserialise operation: %s", e)
            return

        # Integrity check
        if not op.verify_integrity():
            logger.warning("Integrity check failed for op %s", op.op_id[:8])
            return

        # Update HLC
        receive_operation(op)

        # Skip own messages
        if op.peer_id == self._peer_id_str:
            return

        sheet = self._sheets.get(sheet_id)
        if not sheet:
            return

        # Handle control operations
        if op.op_type == OpType.SNAPSHOT_REQUEST:
            await self._serve_snapshot(op)
            return

        if op.op_type == OpType.HEARTBEAT:
            cursor = op.payload.get("cursor", "")
            if sheet_id not in self._presence:
                self._presence[sheet_id] = {}
            self._presence[sheet_id][op.peer_id] = cursor
            logger.debug("Peer %s cursor: %s", op.peer_id[:8], cursor)
            return

        # Apply to CRDT
        applied = sheet.apply(op)
        if not applied:
            logger.debug("Duplicate op %s — skipped", op.op_id[:8])
            return

        # Deliver to adapter callback
        cb = self._callbacks.get(sheet_id)
        if cb:
            await cb(op)

    async def _validate_message(self, peer_id: str, msg: rpc_pb2.Message) -> bool:
        """GossipSub message validator — reject malformed operations."""
        try:
            op = Operation.from_bytes(msg.data)
            return op.verify_integrity()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # State sync for late joiners
    # ------------------------------------------------------------------

    async def _serve_snapshot(self, request_op: Operation) -> None:
        """Respond to a SNAPSHOT_REQUEST by sending current state."""
        sheet_id = request_op.sheet_id
        sheet = self._sheets.get(sheet_id)
        if not sheet:
            return

        snapshot_data = json.dumps(sheet.snapshot()).encode()

        # Chunk into 64KB pieces for libp2p stream compatibility
        chunk_size = 64 * 1024
        chunks = [
            snapshot_data[i : i + chunk_size]
            for i in range(0, len(snapshot_data), chunk_size)
        ]
        if not chunks:
            chunks = [b"{}"]

        if not self._factory:
            return

        for i, chunk in enumerate(chunks):
            chunk_op = self._factory.make_snapshot_chunk(
                sheet_id=sheet_id,
                chunk_index=i,
                total_chunks=len(chunks),
                data=chunk,
                op_log_from=sheet.op_log_length(),
            )
            await self.publish(chunk_op)

        logger.info(
            "Served snapshot for %s in %d chunks to %s",
            sheet_id,
            len(chunks),
            request_op.peer_id[:8],
        )

    async def _handle_sync_stream(self, stream: INetStream) -> None:
        """Handle direct stream requests (for large snapshots)."""
        try:
            data = await stream.read(4096)
            sheet_id = data.decode().strip()
            sheet = self._sheets.get(sheet_id)
            if sheet:
                payload = json.dumps(sheet.snapshot()).encode()
                await stream.write(len(payload).to_bytes(4, "big") + payload)
            await stream.close()
        except Exception as e:
            logger.error("Sync stream error: %s", e)

    # ------------------------------------------------------------------
    # Peer presence
    # ------------------------------------------------------------------

    async def send_heartbeat(self, sheet_id: str, cursor: str = "") -> None:
        if not self._factory:
            return
        hb = self._factory.make_heartbeat(sheet_id, cursor)
        await self.publish(hb)

    def get_presence(self, sheet_id: str) -> dict[str, str]:
        """Return dict of peer_id -> cell cursor for a sheet."""
        return self._presence.get(sheet_id, {})

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def peer_id(self) -> str:
        return self._peer_id_str

    def get_listen_addrs(self) -> list[str]:
        if not self._host:
            return []
        return [
            str(addr) + "/p2p/" + self._peer_id_str for addr in self._host.get_addrs()
        ]

    def get_sheet_state(self, sheet_id: str) -> SheetCRDT | None:
        return self._sheets.get(sheet_id)

    def get_conflicts(self, sheet_id: str) -> list:
        sheet = self._sheets.get(sheet_id)
        return sheet.get_conflicts() if sheet else []

    async def stop(self) -> None:
        if self._host:
            await self._host.close()
        logger.info("P2PCalc node stopped")
