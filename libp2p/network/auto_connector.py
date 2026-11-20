"""
Auto-connector implementation for maintaining minimum connections.

This module provides automatic connection functionality that connects to
known peers when the connection count falls below the low watermark,
matching go-libp2p behavior.

Reference: https://github.com/libp2p/go-libp2p/blob/master/p2p/net/connmgr/connmgr.go
"""

from collections.abc import (
    Awaitable,
    Callable,
)
import ipaddress
import logging
import random
import time
from typing import TYPE_CHECKING

from multiaddr import Multiaddr
import trio

from libp2p.network.config import AUTO_CONNECT_INTERVAL
from libp2p.peer.id import ID
from libp2p.utils.address_validation import is_relay_address

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm


def _ip_is_routable(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """
    Return True if ``ip`` (an ipaddress address) is publicly routable.

    Rejects loopback, link-local, unspecified, multicast, reserved and
    private ranges.  CGNAT (100.64.0.0/10) is treated as routable because
    it is used by Tailscale/WireGuard networks that peers may legitimately
    reach (``ipaddress`` only classifies it as private on Python 3.13+).
    """
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return False
    if getattr(ip, "is_reserved", False):
        return False
    if ip.is_private:
        if (
            isinstance(ip, ipaddress.IPv4Address)
            and (int(ip) & 0xFFC00000) == 0x64400000
        ):  # 100.64.0.0/10
            return True
        return False
    return True


def _addr_is_routable(addr: Multiaddr) -> bool:
    """
    Return True if the multiaddr is dialable from a public node.

    DNS addresses resolve to public IPs and are considered dialable.  For
    IP addresses, only public (non-private, non-loopback) addresses count,
    and *any* public IP component makes the address dialable (multiaddrs
    may embed several IPs, e.g. relay paths).  This prevents the
    auto-connector from wasting dial attempts on Docker-internal peers
    (172.x/10.x) that can never be reached from outside the network.
    """
    try:
        for part in addr.split():
            protos = part.protocols()
            if not protos:
                continue
            proto = protos[0]
            name = getattr(proto, "name", "")
            if name.startswith("dns"):
                return True
            if name not in ("ip4", "ip6"):
                continue
            try:
                ip_str = part.value_for_protocol(name)
            except Exception:
                continue
            if not ip_str:
                continue
            try:
                ip = ipaddress.ip_address(ip_str)
            except Exception:
                continue
            if _ip_is_routable(ip):
                return True
    except Exception:
        return False

    # No IP/DNS component (e.g. relay-only addrs), or only private IPs.
    return False


def _addr_is_direct(addr: Multiaddr) -> bool:
    """
    Return True if ``addr`` is a directly-dialable public address.

    A direct address must be routable (see :func:`_addr_is_routable`) and
    must NOT traverse a relay (``/p2p-circuit``).  Relay paths are only
    usable when a relay client is configured; this node does not use one,
    so dialing them is pure waste — the QUIC transport cannot even derive
    a peer id from a ``/p2p-circuit`` address and fails every attempt.
    """
    if not _addr_is_routable(addr):
        return False
    return not is_relay_address(addr)


def _node_has_public_addr(swarm: "Swarm") -> bool:
    """
    Return True if this node itself announces a public address.

    The check uses the local signed peer record, which reflects the host's
    announced addresses (``announce_addrs`` if configured, otherwise the
    transport addrs plus confirmed observed addresses).  This gates the
    private-address candidate filter: a node that only has private
    addresses (LAN/mDNS deployment) keeps private candidates dialable,
    while a public node skips peers that are only reachable via
    Docker-internal private addresses.
    """
    try:
        local_record = swarm.peerstore.get_local_record()
    except Exception:
        return False
    if local_record is None:
        return False
    try:
        addrs = local_record.record().addrs
    except Exception:
        return False
    return any(_addr_is_routable(a) for a in addrs)


logger = logging.getLogger("libp2p.network.auto_connector")
logger.setLevel(logging.INFO)


class AutoConnector:
    """
    Auto-connector that maintains minimum connection count.

    Periodically checks if the connection count is below the low watermark
    and attempts to connect to known peers from the peer store.

    Similar to go-libp2p's connection manager background dialer.
    """

    def __init__(
        self,
        swarm: "Swarm",
        auto_connect_interval: float = AUTO_CONNECT_INTERVAL,
    ):
        """
        Initialize the auto-connector.

        Parameters
        ----------
        swarm : Swarm
            The swarm instance for connecting
        auto_connect_interval : float
            Interval between auto-connect attempts (seconds)

        """
        self.swarm = swarm
        self.auto_connect_interval = auto_connect_interval
        self._started = False
        self._shutdown_event = trio.Event()
        self._is_connecting = False
        self._in_flight_dials: set[ID] = set()
        self._last_connect_attempt: dict[ID, float] = {}
        self._failure_counts: dict[ID, int] = {}
        self._base_cooldown = 5.0  # base retry interval (seconds, matches go-libp2p)
        self._max_cooldown = 300.0  # cap at 5 minutes for persistent failures
        self._discovery_callback: Callable[[], Awaitable[None]] | None = None
        # Peers that recently disconnected: we back off from immediately
        # re-dialing them (event-driven auto-connect on disconnect would
        # otherwise reconnect to the peer we just closed in a tight loop).
        self._recent_disconnects: dict[ID, float] = {}
        self._disconnect_backoff = 60.0  # seconds
        # Retention-aware dialing: remote peers whose connection managers
        # evict us soon after connect (go-libp2p ConnGarbageCollected,
        # 0x1005) get quarantined so dial budget goes to peers that keep
        # connections open instead of being recycled into the same evictors.
        self._quick_deaths: dict[ID, int] = {}
        self._quick_death_at: dict[ID, float] = {}
        self._quarantine_until: dict[ID, float] = {}
        self._quarantine_count: dict[ID, int] = {}
        self._last_quarantine_at: dict[ID, float] = {}
        self._quick_death_threshold = 45.0  # lifespan below this = eviction
        self._quick_death_limit = 3  # evictions before quarantining
        self._quarantine_base = 90.0  # 90 s, doubles per offense
        self._quarantine_max = 1800.0  # cap at 30 minutes
        # Forgive history: offenses older than this are wiped when a peer
        # re-offends, so an unlucky streak hours ago does not escalate
        # forever (prevents permanent candidate-pool exhaustion).
        self._offense_decay_seconds = 900.0
        # Bound the quarantined set: with heavy churn the set otherwise grows
        # until most candidates are blocked and dialing starves.
        self._quarantine_max_entries = 800
        # Critical poll interval: when the connection count falls below
        # min_connections we poll at _critical_check_interval so the node
        # recovers steadily without overwhelming the CPU (Bug 15).
        self._critical_check_interval = 10.0
        # Observability: per-peer dial outcome history (ring, capped per
        # peer) and cumulative counters so the operator can see when the
        # auto-connector triggered, how many candidates it selected, and
        # what happened to every dial.
        self._dial_history: dict[ID, list[tuple[float, str]]] = {}
        # Diagnostics must not retain every peer seen over the host lifetime.
        # unique_dialed now counts peers in the bounded 30-minute history.
        self._max_tracking_peers = 4096
        self._last_tracking_prune = 0.0
        self._last_emitted_dialed = 0
        self._last_emitted_ok = 0
        self._last_emitted_ok_deadline = 0
        self._last_emitted_timeout = 0
        self._last_emitted_failed = 0
        self._stats: dict[str, int] = {
            "cycles": 0,
            "trigger_disconnect": 0,
            "candidates_seen": 0,
            "candidates_dialable": 0,
            "skip_cooldown": 0,
            "skip_quarantine": 0,
            "skip_disconnect": 0,
            "dialed": 0,
            "ok": 0,
            "ok_after_deadline": 0,
            "timeout": 0,
            "failed": 0,
            "unique_dialed": 0,
        }

    def set_discovery_callback(
        self, callback: Callable[[], Awaitable[None]] | None
    ) -> None:
        """
        Set callback to trigger on-demand DHT discovery when candidates are low.
        """
        self._discovery_callback = callback

    async def start(self) -> None:
        """Start the auto-connector background task."""
        self._started = True
        self._shutdown_event = trio.Event()
        logger.debug("AutoConnector started")

    async def stop(self) -> None:
        """Stop the auto-connector."""
        self._started = False
        self._shutdown_event.set()
        logger.debug("AutoConnector stopped")

    async def run_background_task(self, nursery: trio.Nursery) -> None:
        """
        Run the background task that periodically checks connection count.

        Parameters
        ----------
        nursery : trio.Nursery
            The nursery to run tasks in

        """
        if not self._started:
            return

        nursery.start_soon(self._periodic_check_task)

    async def _periodic_check_task(self) -> None:
        """Periodically check if we need to connect to more peers."""
        while self._started and not self._shutdown_event.is_set():
            try:
                await self.maybe_connect()
            except Exception as e:
                logger.error(f"Error in auto-connect: {e}", exc_info=e)

            # Wait for the next interval or shutdown.  When the connection
            # count is critically below min_connections, poll much more
            # frequently so the node recovers promptly (Bug 15).
            if self._below_min_connections():
                interval = self._critical_check_interval
            else:
                interval = self.auto_connect_interval
            with trio.move_on_after(interval):
                await self._shutdown_event.wait()

    def _below_min_connections(self) -> bool:
        """
        Whether the unique connected peer count is below the critical floor.

        ``min_connections`` is the absolute minimum the connection manager
        tries to keep open; when the count drops below it, the periodic task
        polls at ``_critical_check_interval`` instead of
        ``auto_connect_interval``.

        Counts *unique peers* (not raw connections): multihomed peers hold
        one QUIC + one TCP connection each, so raw connections over-count
        by ~25 % and a raw-based floor would stop dialing while the
        operator's "connected peers" metric was still below target.
        """
        try:
            num_connections = self.swarm.get_connected_peer_count()
            min_connections = self.swarm.connection_config.min_connections
            return num_connections < min_connections
        except Exception:
            return False

    async def maybe_connect(self, trigger: str = "periodic") -> None:
        """
        Check if we should connect to more peers and do so if needed.

        Called periodically by the background task, or can be called
        manually when a peer disconnects.

        Parameters
        ----------
        trigger : str
            What caused this cycle: ``"periodic"`` (timer tick) or
            ``"disconnect"`` (event-driven replenish).  Stored in the
            cycle stats for observability.

        """
        if not self._started:
            return

        if self._is_connecting:
            logger.debug("Auto-connect cycle already in progress, skipping")
            return

        # Reap stale history even when we are already above the dial target.
        self._prune_tracking_caches()
        self._stats["cycles"] += 1
        if trigger == "disconnect":
            self._stats["trigger_disconnect"] += 1

        self._is_connecting = True
        try:
            # Unique connected peers (what operators see and what the
            # watermark targets mean); raw connections can exceed this by
            # ~25 % because multihomed peers hold QUIC + TCP pairs.
            num_connections = self.swarm.get_connected_peer_count()
            raw_connections = self.swarm.get_total_connections()
            low_watermark = self.swarm.connection_config.low_watermark
            min_connections = self.swarm.connection_config.min_connections
            in_flight = len(self._in_flight_dials)

            logger.info(
                "AUTO_CONNECTOR_STATE: peers=%s (raw=%s, in_flight=%s), "
                "low_watermark=%s, min_connections=%s",
                num_connections,
                raw_connections,
                in_flight,
                low_watermark,
                min_connections,
            )

            # Calculate target connections within [low_watermark, high_watermark].
            # Aim for midpoint between low and high watermarks (e.g. 400 for 300-500)
            # so connections stay comfortably above the floor without hitting the
            # pruning ceiling.
            high_watermark = getattr(
                self.swarm.connection_config, "high_watermark", low_watermark
            )
            if high_watermark > low_watermark:
                target = int((low_watermark + high_watermark) / 2)
            else:
                target = low_watermark

            # Only connect if below target (counting in-flight dials)
            if num_connections + in_flight >= target:
                return

            needed = target - (num_connections + in_flight)

            if needed <= 0:
                return

            logger.info(
                "Connections (%s, in_flight=%s) below target (%s, "
                "low_water=%s, high_water=%s); initiating %s new dials",
                num_connections,
                in_flight,
                target,
                low_watermark,
                high_watermark,
                needed,
            )

            # Get candidate peers from peerstore
            candidates = await self._get_candidate_peers()

            # Filter candidates that are not currently in cooldown
            dialable_candidates = [
                p for p in candidates if not self._should_skip_peer(p)
            ]
            # Break down *why* each non-dialable candidate was skipped so
            # the operator can see whether cooldowns, quarantines or the
            # disconnect backoff dominate candidate availability.
            skip_breakdown: dict[str, int] = {}
            for p in candidates:
                reason = self._skip_reason(p)
                if reason:
                    skip_breakdown[reason] = skip_breakdown.get(reason, 0) + 1
            self._stats["candidates_seen"] += len(candidates)
            self._stats["candidates_dialable"] += len(dialable_candidates)
            for reason in ("cooldown", "quarantine", "disconnect"):
                self._stats[f"skip_{reason}"] += skip_breakdown.get(reason, 0)

            # Auto-trigger DHT peer discovery when available candidates are low
            if (
                len(dialable_candidates) < 20
                and needed > 0
                and self._discovery_callback is not None
            ):
                logger.info(
                    "AutoConnector candidate pool low (%d available, needed=%d); "
                    "triggering on-demand DHT discovery",
                    len(dialable_candidates),
                    needed,
                )
                try:
                    await self._discovery_callback()
                except Exception as e:
                    logger.debug("Discovery callback error (non-fatal): %s", e)

            if not candidates:
                logger.debug("No candidate peers available for auto-connection")
                return

            # Shuffle to randomize connection order
            random.shuffle(candidates)

            # Concurrency limiter and dial batch sizing.
            # 32 concurrent dials per ~11s cycle (~2.9 dials/sec) so
            # replenishment outpaces remote connmgr eviction waves instead of
            # merely matching them. The limiter bounds concurrent sockets;
            # the cycle trigger interval bounds total dial rate.
            CONN_MGR_BATCH_SIZE = 32 if needed > 16 else 8
            dial_limiter = trio.CapacityLimiter(CONN_MGR_BATCH_SIZE)
            max_dials_per_cycle = CONN_MGR_BATCH_SIZE

            # Skip peers whose dial attempts have failed too recently (cooldown).
            # This also bounds per-cycle work when the peerstore is dominated by
            # stale/unreachable peers.

            async def _dial_candidate(peer_id: ID) -> None:
                self._in_flight_dials.add(peer_id)
                self._stats["dialed"] += 1
                try:
                    async with dial_limiter:
                        connected = False
                        outcome = "failed"
                        try:
                            logger.debug(f"Auto-connecting to peer {peer_id}")
                            with trio.move_on_after(
                                self.swarm.connection_config.dial_timeout
                            ) as cancel_scope:
                                await self.swarm.dial_peer(peer_id)
                                # only set if dial completes before timeout
                                connected = True
                            if cancel_scope.cancelled_caught:
                                # Dial deadline fired.  The connection may STILL have
                                # been established and registered — Swarm shields
                                # add_conn() registration from this deadline, so a
                                # handshake that completed just before the timeout
                                # lands in the swarm's connection table even though
                                # dial_peer() raised Cancelled.  In that case treat
                                # the dial as a success instead of piling on a
                                # failure cooldown (which would eventually put every
                                # peer in 3600s backoff and strand the node at 0
                                # connections).
                                if self.swarm.get_connections(peer_id):
                                    connected = True
                                    outcome = "ok_after_deadline"
                                    logger.info(
                                        f"Auto-connected to peer {peer_id} "
                                        "(registered despite dial deadline)"
                                    )
                                    self._last_connect_attempt.pop(peer_id, None)
                                    self._failure_counts.pop(peer_id, None)
                                    host = getattr(self.swarm, "host", None)
                                    if host is not None and hasattr(
                                        host, "_schedule_identify"
                                    ):
                                        host._schedule_identify(
                                            peer_id, reason="autoconnect"
                                        )
                                else:
                                    outcome = "timeout"
                                    logger.debug(f"Dial to {peer_id} timed out")
                                    self._failure_counts[peer_id] = (
                                        self._failure_counts.get(peer_id, 0) + 1
                                    )
                                    self._last_connect_attempt[peer_id] = time.time()
                            elif connected:
                                outcome = "ok"
                                logger.info(f"Auto-connected to peer {peer_id}")
                                # Success — clear cooldown so peer is immediately
                                # re-dialable if it disconnects later
                                self._last_connect_attempt.pop(peer_id, None)
                                self._failure_counts.pop(peer_id, None)
                                host = getattr(self.swarm, "host", None)
                                if host is not None and hasattr(
                                    host, "_schedule_identify"
                                ):
                                    host._schedule_identify(
                                        peer_id, reason="autoconnect"
                                    )
                        except Exception as e:
                            logger.debug(f"Failed to auto-connect to {peer_id}: {e}")
                            self._failure_counts[peer_id] = (
                                self._failure_counts.get(peer_id, 0) + 1
                            )
                            self._last_connect_attempt[peer_id] = time.time()
                finally:
                    self._in_flight_dials.discard(peer_id)
                    self._record_dial_outcome(peer_id, outcome)

            try:
                async with trio.open_nursery() as dial_nursery:
                    dialed = 0
                    dial_target = min(needed, max_dials_per_cycle)

                    for peer_id in candidates:
                        if dialed >= dial_target:
                            break

                        if self._should_skip_peer(peer_id):
                            continue

                        dial_nursery.start_soon(_dial_candidate, peer_id)
                        dialed += 1
                        # 10ms stagger between dispatches — prevents CPU
                        # spikes while keeping dispatch overhead under 1.3s
                        # for 128 dials (0.01 × 128 = 1.28s)
                        await trio.sleep(0.01)
            except Exception as e:
                logger.error(f"Error in auto_connect dial nursery: {e}")

            if dialed > 0:
                logger.info(f"Auto-connected to {dialed} new peers")
            self._emit_cycle_stats(
                trigger=trigger,
                num_connections=num_connections,
                raw_connections=raw_connections,
                in_flight=in_flight,
                needed=needed,
                candidates=len(candidates),
                dialable=len(dialable_candidates),
                skip_breakdown=skip_breakdown,
            )
            self._prune_tracking_caches()
        finally:
            self._is_connecting = False

    def _record_dial_outcome(self, peer_id: ID, outcome: str) -> None:
        """
        Record a dial outcome in the per-peer ring and cumulative stats.

        Parameters
        ----------
        peer_id : ID
            The peer that was dialed
        outcome : str
            One of ``ok``, ``ok_after_deadline``, ``timeout``, ``failed``

        """
        if outcome in self._stats:
            self._stats[outcome] += 1
        history = self._dial_history.pop(peer_id, [])
        history.append((time.time(), outcome))
        if len(history) > 20:
            del history[: len(history) - 20]
        self._dial_history[peer_id] = history
        if len(self._dial_history) > self._max_tracking_peers:
            self._dial_history.pop(next(iter(self._dial_history)))
        self._stats["unique_dialed"] = len(self._dial_history)

    def _emit_cycle_stats(
        self,
        trigger: str,
        num_connections: int,
        raw_connections: int,
        in_flight: int,
        needed: int,
        candidates: int,
        dialable: int,
        skip_breakdown: dict[str, int],
    ) -> None:
        """
        Emit the per-cycle, cumulative and repeat-dialer observability lines.

        All three lines use a flat ``key=value`` format so they can be
        grepped and parsed from the logs:
        - ``AUTO_CONNECT_CYCLE``: what this single cycle selected and did
        - ``AUTO_CONNECT_STATS``: cumulative counters since start
        - ``REPEAT_DIALERS``: peers dialed more than twice in the last
          5 minutes (proves or disproves same-peer cycling)
        """
        stats = self._stats
        logger.info(
            "AUTO_CONNECT_CYCLE: trigger=%s peers=%s raw=%s in_flight=%s "
            "needed=%s candidates=%s dialable=%s skip_cooldown=%s "
            "skip_quarantine=%s skip_disconnect=%s dialed=%s ok=%s "
            "ok_after_deadline=%s timeout=%s failed=%s",
            trigger,
            num_connections,
            raw_connections,
            in_flight,
            needed,
            candidates,
            dialable,
            skip_breakdown.get("cooldown", 0),
            skip_breakdown.get("quarantine", 0),
            skip_breakdown.get("disconnect", 0),
            stats["dialed"] - self._last_emitted_dialed,
            stats["ok"] - self._last_emitted_ok,
            stats["ok_after_deadline"] - self._last_emitted_ok_deadline,
            stats["timeout"] - self._last_emitted_timeout,
            stats["failed"] - self._last_emitted_failed,
        )
        self._last_emitted_dialed = stats["dialed"]
        self._last_emitted_ok = stats["ok"]
        self._last_emitted_ok_deadline = stats["ok_after_deadline"]
        self._last_emitted_timeout = stats["timeout"]
        self._last_emitted_failed = stats["failed"]

        repeats, repeat_total = self._repeat_dialers(window=300.0, min_count=3)
        logger.info(
            "AUTO_CONNECT_STATS: cycles=%s trigger_disconnect=%s "
            "candidates_seen=%s candidates_dialable=%s dialed=%s ok=%s "
            "ok_after_deadline=%s timeout=%s failed=%s recent_unique_dialed=%s "
            "repeat_peers=%s repeat_dials_5m=%s",
            stats["cycles"],
            stats["trigger_disconnect"],
            stats["candidates_seen"],
            stats["candidates_dialable"],
            stats["dialed"],
            stats["ok"],
            stats["ok_after_deadline"],
            stats["timeout"],
            stats["failed"],
            stats["unique_dialed"],
            len(repeats),
            repeat_total,
        )
        if repeats:
            logger.info(
                "REPEAT_DIALERS: %s",
                ",".join(f"{pid}:{count}" for pid, count in repeats),
            )

    def _repeat_dialers(
        self, window: float = 300.0, min_count: int = 3
    ) -> tuple[list[tuple[str, int]], int]:
        """
        Peers dialed ``>= min_count`` times within the last ``window``
        seconds, sorted by dial count descending.  Also returns the total
        number of repeat dials (dials beyond the first per peer) in the
        window.
        """
        now = time.time()
        counts: dict[ID, int] = {}
        for peer_id, history in self._dial_history.items():
            n = sum(1 for ts, _ in history if now - ts <= window)
            if n >= min_count:
                counts[peer_id] = n
        repeats = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
        repeat_total = sum(n - 1 for n in counts.values())
        return [(str(pid), n) for pid, n in repeats], repeat_total

    def _prune_tracking_caches(self) -> None:
        """Prune tracking dictionaries to prevent memory accumulation."""
        now = time.time()
        if now - self._last_tracking_prune < 30.0:
            return
        self._last_tracking_prune = now
        if self._last_connect_attempt:
            stale_keys = [
                pid
                for pid, ts in self._last_connect_attempt.items()
                if now - ts > self._max_cooldown
            ]
            for pid in stale_keys:
                self._last_connect_attempt.pop(pid, None)
                self._failure_counts.pop(pid, None)

        if self._recent_disconnects:
            stale_disc = [
                pid
                for pid, ts in self._recent_disconnects.items()
                if now - ts > self._disconnect_backoff * 2
            ]
            for pid in stale_disc:
                self._recent_disconnects.pop(pid, None)

        if self._quarantine_until:
            expired = [
                pid for pid, until in self._quarantine_until.items() if now - until > 0
            ]
            for pid in expired:
                self._quarantine_until.pop(pid, None)
                self._quarantine_count.pop(pid, None)
                self._quick_deaths.pop(pid, None)
                self._quick_death_at.pop(pid, None)
                self._last_quarantine_at.pop(pid, None)

        for pid, timestamp in list(self._quick_death_at.items()):
            if pid not in self._quarantine_until and (
                now - timestamp > self._offense_decay_seconds
            ):
                self._quick_death_at.pop(pid, None)
                self._quick_deaths.pop(pid, None)

        # TTLs bound age; caps also bound high-churn bursts between expirations.
        for tracking in (self._last_connect_attempt, self._recent_disconnects):
            overflow = len(tracking) - self._max_tracking_peers
            if overflow > 0:
                oldest = sorted(tracking, key=lambda pid: tracking[pid])[:overflow]
                for pid in oldest:
                    tracking.pop(pid, None)
                    if tracking is self._last_connect_attempt:
                        self._failure_counts.pop(pid, None)
        overflow = len(self._quick_deaths) - self._max_tracking_peers
        if overflow > 0:
            candidates = sorted(
                (
                    pid
                    for pid in self._quick_death_at
                    if pid not in self._quarantine_until
                ),
                key=lambda pid: self._quick_death_at[pid],
            )
            for pid in candidates[:overflow]:
                self._quick_deaths.pop(pid, None)
                self._quick_death_at.pop(pid, None)

        if self._dial_history:
            stale_history = [
                pid
                for pid, history in self._dial_history.items()
                if not history or now - history[-1][0] > 1800.0
            ]
            for pid in stale_history:
                self._dial_history.pop(pid, None)
        self._stats["unique_dialed"] = len(self._dial_history)

    async def _get_candidate_peers(self) -> list[ID]:
        """
        Get candidate peers for auto-connection.

        Returns peers from the peerstore that we're not currently
        connected to and have addresses available.

        Returns
        -------
        list[ID]
            List of candidate peer IDs

        """
        candidates = []

        # Get all peers from peerstore (sample bounded query when available)
        if hasattr(self.swarm.peerstore, "sample_peer_ids"):
            all_peers = self.swarm.peerstore.sample_peer_ids(
                limit=200, random_order=True
            )
        else:
            all_peers = self.swarm.peerstore.peer_ids()

        # Get currently connected peers
        connected_peers = set(self.swarm.connections.keys())

        # Only apply the private-address filter when this node itself is a
        # public node.  On a LAN/mDNS deployment (all-local addresses) peers
        # with private addresses must stay dialable.
        filter_private = _node_has_public_addr(self.swarm)

        for peer_id in all_peers:
            # Skip ourselves
            if peer_id == self.swarm.self_id:
                continue

            # Skip already connected peers
            if peer_id in connected_peers:
                continue

            # Check if peer has addresses
            try:
                addrs = self.swarm.peerstore.addrs(peer_id)
                if not addrs:
                    continue
                if filter_private and not any(_addr_is_direct(a) for a in addrs):
                    # Peers whose *only* addresses are unusable from a public
                    # node are skipped instead of burning dial attempts:
                    # private-only (Docker-internal 172.x/10.x, loopback,
                    # etc.) or relay-only (``/p2p-circuit``) paths can never
                    # be dialed directly.
                    continue

                # Filter out peers with no addresses supported by registered transports
                if (
                    hasattr(self.swarm, "transport_manager")
                    and self.swarm.transport_manager is not None
                    and not any(
                        self.swarm.transport_manager.transport_for_dialing(a)
                        is not None
                        for a in addrs
                    )
                ):
                    continue

                candidates.append(peer_id)
            except Exception:
                continue

        return candidates

    def _get_cooldown(self, peer_id: ID) -> float:
        """
        Calculate exponential backoff cooldown for a peer matching go-libp2p standards.

        Returns base_cooldown * 2^(failures-1), capped at max_cooldown.
        First failure: 5s, second: 15s, third: 20s, fourth: 40s … cap: 300s.
        When critically below min_connections floor, cap backoff at 60s.

        Parameters
        ----------
        peer_id : ID
            The peer to calculate cooldown for

        Returns
        -------
        float
            Cooldown duration in seconds

        """
        n = self._failure_counts.get(peer_id, 0)
        if n <= 0:
            return 0.0
        if n == 1:
            backoff = self._base_cooldown  # 5.0s
        elif n == 2:
            backoff = self._base_cooldown * 3.0  # 15.0s
        else:
            backoff = min(self._base_cooldown * (2 ** (n - 1)), self._max_cooldown)

        if self._below_min_connections():
            return min(backoff, 60.0)
        return min(backoff, self._max_cooldown)

    def _should_skip_peer(self, peer_id: ID) -> bool:
        """
        Check if we should skip connecting to a peer.

        Skips peers that we recently tried to connect to (exponential backoff).

        Parameters
        ----------
        peer_id : ID
            The peer to check

        Returns
        -------
        bool
            True if we should skip this peer

        """
        last_attempt = self._last_connect_attempt.get(peer_id)
        if last_attempt is not None:
            if time.time() - last_attempt < self._get_cooldown(peer_id):
                return True

        # Back off recently-disconnected peers so a disconnect-triggered
        # auto-connect does not immediately re-dial the peer we just lost.
        last_disconnect = self._recent_disconnects.get(peer_id)
        if last_disconnect is not None:
            if time.time() - last_disconnect < self._disconnect_backoff:
                return True

        # Skip quarantined peers: remote connmgr eviction (quick deaths)
        # marks a peer as a slot-scarce evictor — re-dialing it only burns
        # the dial budget and recycles connections into the same churn.
        quarantine_until = self._quarantine_until.get(peer_id)
        if quarantine_until is not None:
            if time.time() < quarantine_until:
                return True

        return False

    def _skip_reason(self, peer_id: ID) -> str | None:
        """
        Return the reason this peer is currently skipped, or None.

        Mirrors the checks in :meth:`_should_skip_peer` so the skip
        breakdown can be logged.

        Parameters
        ----------
        peer_id : ID
            The peer to check

        Returns
        -------
        str | None
            ``"cooldown"``, ``"disconnect"``, ``"quarantine"``, or None

        """
        last_attempt = self._last_connect_attempt.get(peer_id)
        if last_attempt is not None:
            if time.time() - last_attempt < self._get_cooldown(peer_id):
                return "cooldown"

        last_disconnect = self._recent_disconnects.get(peer_id)
        if last_disconnect is not None:
            if time.time() - last_disconnect < self._disconnect_backoff:
                return "disconnect"

        quarantine_until = self._quarantine_until.get(peer_id)
        if quarantine_until is not None:
            if time.time() < quarantine_until:
                return "quarantine"

        return None

    def record_successful_connection(self, peer_id: ID) -> None:
        """
        Record a successful connection to a peer.

        Clears the cooldown for this peer.

        Parameters
        ----------
        peer_id : ID
            The peer that we connected to

        """
        self._last_connect_attempt.pop(peer_id, None)
        self._failure_counts.pop(peer_id, None)
        self._recent_disconnects.pop(peer_id, None)

    def record_disconnect(self, peer_id: ID, lifespan: float | None = None) -> None:
        """
        Record that a connection to a peer closed.

        The auto-connector will not attempt to re-dial this peer for
        ``_disconnect_backoff`` seconds, avoiding immediate reconnect loops
        when disconnects trigger auto-connect (Bug 6 fixup).

        Connections that die quickly (``lifespan`` below
        ``_quick_death_threshold``, i.e. the remote evicted us shortly
        after connect) count toward a quarantine: after
        ``_quick_death_limit`` evictions the peer is skipped for
        ``_quarantine_base`` (escalating, capped at ``_quarantine_max``)
        so the dial budget goes to peers that keep connections open.

        Parameters
        ----------
        peer_id : ID
            The peer that disconnected
        lifespan : float | None
            Connection duration in seconds, or None if unknown

        """
        now = time.time()
        self._recent_disconnects.pop(peer_id, None)
        self._recent_disconnects[peer_id] = now
        if len(self._recent_disconnects) > self._max_tracking_peers:
            self._recent_disconnects.pop(next(iter(self._recent_disconnects)))

        if lifespan is None or lifespan >= self._quick_death_threshold:
            # Survived long enough — a keeper, not an evictor.  Reset any
            # prior quick-death streak so soft blips do not accumulate.
            if lifespan is not None:
                self._quick_deaths.pop(peer_id, None)
                self._quick_death_at.pop(peer_id, None)
            return

        if now - self._quick_death_at.get(peer_id, now) > self._offense_decay_seconds:
            self._quick_deaths.pop(peer_id, None)
        count = self._quick_deaths.get(peer_id, 0) + 1
        self._quick_deaths[peer_id] = count
        self._quick_death_at[peer_id] = now
        if count < self._quick_death_limit:
            return

        now = time.time()
        # Offense decay: a long gap since the last quarantine means the
        # earlier streak is stale — start over at offense 1 instead of
        # escalating on months-old history.
        if now - self._last_quarantine_at.get(peer_id, 0.0) > (
            self._offense_decay_seconds
        ):
            self._quarantine_count[peer_id] = 0

        offense = self._quarantine_count.get(peer_id, 0) + 1
        self._quarantine_count[peer_id] = offense
        self._last_quarantine_at[peer_id] = now
        duration = min(
            self._quarantine_base * (2 ** (offense - 1)), self._quarantine_max
        )
        self._enforce_quarantine_cap()
        self._quarantine_until[peer_id] = now + duration
        logger.info(
            "QUARANTINE: peer %s evicted %s quick conns (last lifespan %.0fs, "
            "offense %d); not dialing for %.0fs",
            peer_id,
            count,
            lifespan,
            offense,
            duration,
        )

    def _enforce_quarantine_cap(self) -> None:
        """
        Bound the quarantine set so candidate exhaustion cannot starve dialing.

        When more than ``_quarantine_max_entries`` peers are quarantined,
        release the bans that expire soonest — they are nearly dialable
        anyway, and a bounded set keeps the candidate pool alive under
        heavy churn.
        """
        excess = len(self._quarantine_until) - self._quarantine_max_entries
        if excess <= 0:
            return
        soonest = sorted(self._quarantine_until.items(), key=lambda kv: kv[1])
        for pid, _until in soonest[:excess]:
            self._quarantine_until.pop(pid, None)
            self._quarantine_count.pop(pid, None)
            self._quick_deaths.pop(pid, None)
            self._quick_death_at.pop(pid, None)
            self._last_quarantine_at.pop(pid, None)
        logger.info(
            "QUARANTINE: set exceeded %d entries; released %d soonest-expiring "
            "bans to keep the candidate pool dialable",
            self._quarantine_max_entries,
            excess,
        )

    def record_failed_connection(self, peer_id: ID) -> None:
        """
        Record a failed connection attempt.

        Updates the last attempt time for cooldown purposes.

        Parameters
        ----------
        peer_id : ID
            The peer we failed to connect to

        """
        self._failure_counts[peer_id] = self._failure_counts.get(peer_id, 0) + 1
        self._last_connect_attempt[peer_id] = time.time()

    def clear_cooldown(self, peer_id: ID) -> None:
        """
        Clear the cooldown for a specific peer.

        Parameters
        ----------
        peer_id : ID
            The peer to clear cooldown for

        """
        self._last_connect_attempt.pop(peer_id, None)
        self._failure_counts.pop(peer_id, None)
        self._recent_disconnects.pop(peer_id, None)

    def clear_all_cooldowns(self) -> None:
        """Clear all peer cooldowns and failure counts."""
        self._last_connect_attempt.clear()
        self._failure_counts.clear()
        self._recent_disconnects.clear()
        self._quick_deaths.clear()
        self._quick_death_at.clear()
        self._quarantine_until.clear()
        self._quarantine_count.clear()
        self._last_quarantine_at.clear()
        self._dial_history.clear()
