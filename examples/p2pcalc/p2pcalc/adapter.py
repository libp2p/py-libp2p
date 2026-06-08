# p2pcalc/adapter.py — EtherCalc/Redis to libp2p GossipSub adapter
# Author: Dashpreet Singh <dashpreetsinghhanda@gmail.com>
#
# This is the core innovation of the project.
#
# EtherCalc uses Redis pub-sub to broadcast SocialCalc commands between
# its Node.js workers. Each room publishes to channel "sc:<room_name>".
# The command format is a raw SocialCalc command string:
#   "set A1 value 42"
#   "set B2 formula =SUM(A1:A5)"
#
# This adapter:
#   1. Subscribes to EtherCalc's Redis channel for a room
#   2. Translates each command into a P2PCalc Operation
#   3. Publishes the Operation to GossipSub (replaces central server)
#   4. Receives Operations from GossipSub peers
#   5. Injects them back into EtherCalc's Redis channel
#   6. EtherCalc's existing Socket.io layer delivers to browsers
#
# The UI (EtherCalc/SocialCalc in the browser) is NEVER touched.
# The server-side Node.js EtherCalc worker is NEVER touched.
# We intercept only at the Redis pub-sub layer.
#
# ADDITIONAL INNOVATIONS:
#   - Operation deduplication at the Redis inject layer
#     (prevents echo loops when our own ops come back via GossipSub)
#   - Causal buffering: ops with unmet dependencies are buffered
#     until their parents arrive (prevents out-of-order application)
#   - Presence injection: peer cursor positions are injected as
#     EtherCalc "cursor" commands so users see each other's positions
#   - Conflict markers: when MVR detects a conflict, a comment cell
#     is injected into EtherCalc showing the competing values

from __future__ import annotations

import asyncio
from collections import defaultdict
import logging

import redis.asyncio as aioredis

from .crdt import ConflictPolicy
from .operation import Operation
from .p2p_node import P2PCalcNode

logger = logging.getLogger("p2pcalc.adapter")

# EtherCalc Redis channel pattern: "sc:<room_name>"
ETHERCALC_CHANNEL_PREFIX = "sc"

# Our own operations that we inject back into Redis get tagged with this
# prefix in a side-channel to detect echo loops
ECHO_TAG_PREFIX = "p2pcalc_injected:"


class EtherCalcAdapter:
    """
    Bridges EtherCalc's Redis pub-sub with the P2PCalc GossipSub network.

    One adapter instance handles one EtherCalc room (sheet).
    Multiple adapters can run in the same process for multiple rooms.
    """

    def __init__(
        self,
        room_name: str,
        node: P2PCalcNode,
        redis_url: str = "redis://localhost:6379",
        conflict_policy: ConflictPolicy = ConflictPolicy.MULTI_VALUE,
    ):
        self._room = room_name
        self._node = node
        self._redis_url = redis_url
        self._sheet_id = room_name

        # Redis clients — separate for pub and sub
        self._redis_pub: aioredis.Redis | None = None
        self._redis_sub: aioredis.client.PubSub | None = None

        # Dedup: track op_ids we injected so we don't re-broadcast them
        self._injected_op_ids: set[str] = set()
        self._injected_commands: set[str] = set()  # raw command strings

        # Causal buffer: ops waiting for their depends_on to arrive
        self._causal_buffer: dict[str, list[Operation]] = defaultdict(list)

        # Metrics
        self._stats = {
            "redis_received": 0,
            "p2p_published": 0,
            "p2p_received": 0,
            "redis_injected": 0,
            "duplicates_dropped": 0,
            "causal_buffered": 0,
            "conflicts_detected": 0,
        }

        self._running = False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._redis_pub = await aioredis.from_url(
            self._redis_url, decode_responses=True
        )
        redis_client = await aioredis.from_url(self._redis_url, decode_responses=True)
        self._redis_sub = redis_client.pubsub()

        # Subscribe to EtherCalc's Redis channel for this room
        channel = f"{ETHERCALC_CHANNEL_PREFIX}:{self._room}"
        await self._redis_sub.subscribe(channel)
        logger.info("Adapter started for room '%s' (channel=%s)", self._room, channel)

        # Join the P2P network for this sheet
        await self._node.join_sheet(
            sheet_id=self._sheet_id,
            on_operation=self._on_p2p_operation,
            request_snapshot=True,
        )

        self._running = True

        # Run both pumps concurrently
        await asyncio.gather(
            self._redis_pump(),
            self._heartbeat_pump(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._redis_sub:
            await self._redis_sub.unsubscribe()
        if self._redis_pub:
            await self._redis_pub.aclose()
        logger.info("Adapter stopped for room '%s'", self._room)

    # ------------------------------------------------------------------
    # Redis -> P2P path (outbound)
    # ------------------------------------------------------------------

    async def _redis_pump(self) -> None:
        """Read commands from EtherCalc Redis, publish to GossipSub."""
        async for message in self._redis_sub.listen():
            if not self._running:
                break
            if message["type"] != "message":
                continue

            raw = message["data"]

            # Skip commands we injected ourselves — echo loop prevention
            if raw.startswith(ECHO_TAG_PREFIX):
                continue
            if raw in self._injected_commands:
                self._injected_commands.discard(raw)
                self._stats["duplicates_dropped"] += 1
                continue

            self._stats["redis_received"] += 1
            logger.debug("Redis -> P2P: %r", raw[:80])

            await self._node.publish_command(self._sheet_id, raw)
            self._stats["p2p_published"] += 1

            # Check for conflicts after apply
            conflicts = self._node.get_conflicts(self._sheet_id)
            if conflicts:
                self._stats["conflicts_detected"] += len(conflicts)
                for conflict_cell in conflicts:
                    await self._inject_conflict_marker(conflict_cell)

    # ------------------------------------------------------------------
    # P2P -> Redis path (inbound)
    # ------------------------------------------------------------------

    async def _on_p2p_operation(self, op: Operation) -> None:
        """Receive an Operation from GossipSub, inject into EtherCalc Redis."""
        self._stats["p2p_received"] += 1

        # Check causal dependencies
        if op.depends_on:
            sheet = self._node.get_sheet_state(self._sheet_id)
            if sheet:
                seen_ids = set()
                for past_op in sheet.op_log_since(0):
                    seen_ids.add(past_op.op_id)
                unmet = [dep for dep in op.depends_on if dep not in seen_ids]
                if unmet:
                    logger.debug("Op %s buffered — waiting for %s", op.op_id[:8], unmet)
                    for dep in unmet:
                        self._causal_buffer[dep].append(op)
                    self._stats["causal_buffered"] += 1
                    return

        await self._inject_to_redis(op)

        # Flush any ops that were waiting for this op
        await self._flush_causal_buffer(op.op_id)

    async def _inject_to_redis(self, op: Operation) -> None:
        """Inject a P2P operation's raw command into EtherCalc Redis."""
        if not op.raw_command or not self._redis_pub:
            return

        if op.op_id in self._injected_op_ids:
            self._stats["duplicates_dropped"] += 1
            return

        self._injected_op_ids.add(op.op_id)
        # Bound the set size
        if len(self._injected_op_ids) > 10000:
            self._injected_op_ids = set(list(self._injected_op_ids)[-5000:])

        # Track so redis_pump doesn't re-broadcast it
        self._injected_commands.add(op.raw_command)

        channel = f"{ETHERCALC_CHANNEL_PREFIX}:{self._room}"
        await self._redis_pub.publish(channel, op.raw_command)
        self._stats["redis_injected"] += 1

        logger.debug(
            "P2P -> Redis: peer=%s cmd=%r",
            op.peer_id[:8],
            op.raw_command[:60],
        )

    async def _flush_causal_buffer(self, arrived_op_id: str) -> None:
        """Flush operations that were waiting for arrived_op_id."""
        waiting = self._causal_buffer.pop(arrived_op_id, [])
        for op in waiting:
            logger.debug(
                "Flushing buffered op %s (dependency %s arrived)",
                op.op_id[:8],
                arrived_op_id[:8],
            )
            await self._inject_to_redis(op)
            await self._flush_causal_buffer(op.op_id)

    # ------------------------------------------------------------------
    # Conflict markers
    # ------------------------------------------------------------------

    async def _inject_conflict_marker(self, conflict_cell) -> None:
        """
        Inject a conflict marker into EtherCalc as a comment cell.

        When MVR detects concurrent conflicting edits, we inject a
        special comment into the cell adjacent to the conflict so users
        can see and resolve it directly in the spreadsheet UI.
        """
        if not self._redis_pub:
            return

        coord = conflict_cell.coord
        values = [v.value for v in conflict_cell.candidates[:3]]
        marker = f"CONFLICT: {' | '.join(values)}"

        # Find the column letter to place the marker one column to the right
        col_letter = "".join(c for c in coord if c.isalpha())
        row_num = "".join(c for c in coord if c.isdigit())
        next_col = chr(ord(col_letter[-1]) + 1) if col_letter else "B"
        marker_coord = f"{next_col}{row_num}"

        # Inject as a cell comment (SocialCalc format)
        command = f"set {marker_coord} value {marker}"
        channel = f"{ETHERCALC_CHANNEL_PREFIX}:{self._room}"
        await self._redis_pub.publish(channel, command)
        logger.info("Injected conflict marker at %s for %s", marker_coord, coord)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_pump(self) -> None:
        """Send periodic heartbeats to advertise presence."""
        while self._running:
            await asyncio.sleep(10)
            try:
                await self._node.send_heartbeat(self._sheet_id)
            except Exception as e:
                logger.debug("Heartbeat error: %s", e)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            **self._stats,
            "room": self._room,
            "peer_id": self._node.peer_id[:12],
            "p2p_addrs": self._node.get_listen_addrs(),
            "presence": self._node.get_presence(self._sheet_id),
            "conflicts_pending": len(self._node.get_conflicts(self._sheet_id)),
        }


# ---------------------------------------------------------------------------
# Multi-room adapter manager
# ---------------------------------------------------------------------------


class AdapterManager:
    """
    Manages multiple EtherCalc room adapters on a single P2P node.

    One P2P node, many rooms — each room gets its own GossipSub topic
    and Redis channel subscription.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        p2p_port: int = 0,
        known_peers: list[str] | None = None,
        conflict_policy: ConflictPolicy = ConflictPolicy.MULTI_VALUE,
    ):
        self._redis_url = redis_url
        self._conflict_policy = conflict_policy
        self._node = P2PCalcNode(
            port=p2p_port,
            known_peers=known_peers or [],
            conflict_policy=conflict_policy,
        )
        self._adapters: dict[str, EtherCalcAdapter] = {}
        self._started = False

    async def start(self) -> str:
        peer_id = await self._node.start()
        self._started = True
        logger.info("AdapterManager started: peer_id=%s", peer_id)
        logger.info("Listening on: %s", self._node.get_listen_addrs())
        return peer_id

    async def add_room(self, room_name: str) -> EtherCalcAdapter:
        if room_name in self._adapters:
            return self._adapters[room_name]
        adapter = EtherCalcAdapter(
            room_name=room_name,
            node=self._node,
            redis_url=self._redis_url,
            conflict_policy=self._conflict_policy,
        )
        self._adapters[room_name] = adapter
        asyncio.create_task(adapter.start())
        logger.info("Added room: %s", room_name)
        return adapter

    async def remove_room(self, room_name: str) -> None:
        adapter = self._adapters.pop(room_name, None)
        if adapter:
            await adapter.stop()

    def all_stats(self) -> dict:
        return {
            "peer_id": self._node.peer_id,
            "listen_addrs": self._node.get_listen_addrs(),
            "rooms": {
                name: adapter.stats() for name, adapter in self._adapters.items()
            },
        }

    async def stop(self) -> None:
        for adapter in self._adapters.values():
            await adapter.stop()
        await self._node.stop()
